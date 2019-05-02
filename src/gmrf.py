'''
Created on Feb 8, 2017

@author: hans-werner
'''
from assembler import Assembler
from assembler import Kernel
from assembler import IIForm
from assembler import Form
from assembler import IPForm
from assembler import GaussRule

from fem import Element
from fem import DofHandler
from fem import Basis

from function import Function
from function import Nodal
from function import Explicit
from function import Constant

from mesh import Mesh1D
from mesh import QuadMesh


from numbers import Number, Real
import numpy as np
from scipy import linalg
from scipy.special import kv, gamma
import scipy.sparse as sp
from scipy.sparse import linalg as spla
from sksparse.cholmod import cholesky, cholesky_AAt, Factor, CholmodNotPositiveDefiniteError  # @UnresolvedImport

def modchol_ldlt(A,delta=None):
    """
    Modified Cholesky algorithm based on LDL' factorization.
    [L D,P,D0] = modchol_ldlt(A,delta) computes a modified
    Cholesky factorization P*(A + E)*P' = L*D*L', where 
    P is a permutation matrix, L is unit lower triangular,
    and D is block diagonal and positive definite with 1-by-1 and 2-by-2 
    diagonal blocks.  Thus A+E is symmetric positive definite, but E is
    not explicitly computed.  Also returned is a block diagonal D0 such
    that P*A*P' = L*D0*L'.  If A is sufficiently positive definite then 
    E = 0 and D = D0.  
    The algorithm sets the smallest eigenvalue of D to the tolerance
    delta, which defaults to sqrt(eps)*norm(A,'fro').
    The LDL' factorization is compute using a symmetric form of rook 
    pivoting proposed by Ashcraft, Grimes and Lewis.
    
    Reference:
    S. H. Cheng and N. J. Higham. A modified Cholesky algorithm based
    on a symmetric indefinite factorization. SIAM J. Matrix Anal. Appl.,
    19(4):1097-1110, 1998. doi:10.1137/S0895479896302898,

    Authors: Bobby Cheng and Nick Higham, 1996; revised 2015.
    """
    assert np.allclose(A, A.T, atol=1e-12), \
    'Input "A" must be symmetric'    

    if delta is None:
        eps = np.finfo(float).eps
        delta = np.sqrt(eps)*linalg.norm(A, 'fro')
        #delta = 1e-5*linalg.norm(A, 'fro')
    else:
        assert delta>0, 'Input "delta" should be positive.'

    n = max(A.shape)

    L,D,p = linalg.ldl(A)  # @UndefinedVariable
    DMC = np.eye(n)
        
    # Modified Cholesky perturbations.
    k = 0
    while k < n:
        one_by_one = False
        if k == n-1:
            one_by_one = True
        elif D[k,k+1] == 0:
            one_by_one = True
            
        if one_by_one:
            #            
            # 1-by-1 block
            #
            if D[k,k] <= delta:
                DMC[k,k] = delta
            else:
                DMC[k,k] = D[k,k]
         
            k += 1
      
        else:  
            #            
            # 2-by-2 block
            #
            E = D[k:k+2,k:k+2]
            T,U = linalg.eigh(E)
            T = np.diag(T)
            for ii in range(2):
                if T[ii,ii] <= delta:
                    T[ii,ii] = delta
            
            temp = np.dot(U,np.dot(T,U.T))
            DMC[k:k+2,k:k+2] = (temp + temp.T)/2  # Ensure symmetric.
            k += 2

    P = sp.diags([1],0,shape=(n,n), format='coo') 
    P.row = P.row[p]
    P = P.tocsr()
    
    #ld = np.diagonal(P.dot(L))
    #if any(np.abs(ld)<1e-15):
    #    print('L is singular')
        
    return L, DMC, P, D
    
    
def diagonal_inverse(d, eps=None):
    """
    Compute the (approximate) pseudo-inverse of a diagonal matrix with
    diagonal entries d. 
    
    Inputs:
    
        d: double, (n, ) vector of diagonal entries
        
        eps: cut-off tolerance for zero entries
    """
    if eps is None:
        eps = np.finfo(float).eps
    else:
        assert eps > 0, 'Input "eps" should be positive.'
    
    if len(d.shape)==2:
        #
        # Matrix
        # 
        d = d.diagonal()
        
    d_inv = np.zeros(d.shape)
    i_nz = np.abs(d)>eps
    d_inv[i_nz] = 1/d[i_nz]
    D_inv = np.diag(d_inv)
    
    return D_inv


# =============================================================================
# Covariance Functions
# =============================================================================
"""
Commonly used covariance functions

For each function, we assume the input is given by two d-dimensional
vectors of length n. 
"""
def distance(x, y, M=None, periodic=False, box=None):
    """
    Compute the Euclidean distance vector between rows in x and rows in y
    
    Inputs: 
    
        x,y: two (n,dim) arrays
        
        M: double, positive semidefinite anistropy coefficient 
        
        periodic: bool [False], indicates a toroidal domain
        
        box: double, tuple representing the bounding box, i.e. 
            1D: box = (x_min, x_max)
            2D: box = (x_min, x_max, y_min, y_max) 
            If periodic is True, then box should be specified.
        
    Outputs: 
    
        d: double, (n,1) vector ||x[i]-y[i]||_M of (M-weighted) 
            Euclidean distances
         
    """
    # Check wether x and y have the same dimensions 
    assert x.shape == y.shape, 'Vectors x and y have incompatible shapes.'
    dim = x.shape[1]
    
    if dim==1:
        #
        # 1D
        #
        # Periodicity
        if periodic:
            assert box is not None, \
            'If periodic, bounding box must be specified.'
            
            x_min, x_max = box
            w  = x_max - x_min
            dx = np.min(np.array([np.abs(x-y), w - np.abs(x-y)]),axis=0)
        else:
            dx = np.abs(x-y)
        # "Anisotropy"    
        if M is None:
            return dx
        else:
            assert isinstance(M, Real) and M>=0, \
            'For one dimensional covariance, input "M" '+\
            'is a positive number.'
            return np.sqrt(M)*dx
    elif dim==2:
        #
        # 2D
        #   
        dx = np.abs(x[:,0]-y[:,0])
        dy = np.abs(x[:,1]-y[:,1])
        if periodic:
            assert box is not None, \
            'If periodic, bounding box must be specified.'
            x_min, x_max, y_min, y_max = box
            dx = np.min(np.array([dx,(x_max-x_min)-dx]),axis=0)
            dy = np.min(np.array([dy,(y_max-y_min)-dy]),axis=0)
        
        if M is None:
            return np.sqrt(dx**2 + dy**2)
        else:
            assert all(np.linalg.eigvals(M)>=0) and \
                   np.allclose(M,M.transpose()),\
                   'M should be symmetric positive definite.'
            
            ddx = np.array([dx,dy])
            Mddx = np.dot(M, ddx).T
            return np.sqrt(np.sum(ddx.T*Mddx, axis=1))


def constant(x,y,sgm=1):
    """
    Constant covariance kernel
    
        C(x,y) = sgm
    
    Inputs: 
    
        x,y: double, two (n,d) arrays
        
        sgm: double >0, standard deviation
            
    Outputs:
    
        double, (n,) array of covariances  
    """
    assert x.shape == y.shape, \
    'Input arrays have incompatible shapes.'
    
    return sgm*np.ones(x.shape[0])

    
def linear(x,y,sgm=1, M=None):
    """
    Linear covariance
    
        C(x,y) = sgm^2 + <x,My>  (Euclidean inner product)
        
    Inputs: 
    
        x,y: double, (n,dim) np.array of points
        
        sgm: double >0, standard deviation
        
        M: double, positive definite anisotropy tensor 
     
    """
    dim = x.shape[1]
    if dim==1:
        #
        # 1D
        # 
        if M is None:
            sgm**2 + x*y
            return sgm**2 + x*y
        else:
            assert isinstance(M,Real), 'Input "M" should be a scalar.'
            return x*M*y
        
    elif dim==2:
        #
        # 2D
        #  
        if M is None:
            return sgm**2 + np.sum(x*y, axis=1)
        else:
            assert M.shape == (2,2), 'Input "M" should be a 2x2 matrix.'
            My = np.dot(M, y.T).T
            return sgm**2 + np.sum(x*My, axis=1)
    else: 
        raise Exception('Only 1D and 2D supported.')


def gaussian(x, y, sgm=1, l=1, M=None, periodic=False):
    """
    Squared exponential covariance function
    
        C(x,y) = exp(-|x-y|^2/(2l^2))
    
    """
    d = distance(x, y, M, periodic=periodic)
    return sgm**2*np.exp(-d**2/(2*l**2))


def exponential(x, y, sgm=1, l=0.1, M=None, periodic=False):
    """
    Exponential covariance function
    
        C(x,y) = exp(-|x-y|/l)
        
    Inputs: 
    
        x,y: np.array, spatial points
        
        l: range parameter
    """
    d = distance(x, y, M, periodic=periodic)
    return sgm**2*np.exp(-d/l)


def matern(x, y, sgm, nu, l, M=None, periodic=False):
    """
    Matern covariance function
    
    Inputs:
    
        x,y: np.array, spatial points
        
        sgm: variance
        
        nu: shape parameter (k times differentiable if nu > k)
        
        l: range parameter 
        
    Source: 
    """
    d = distance(x, y, M, periodic=periodic)
    K = sgm**2*2**(1-nu)/gamma(nu)*(np.sqrt(2*nu)*d/l)**nu*\
        kv(nu,np.sqrt(2*nu)*d/l)
    #
    # Modified Bessel function undefined at d=0, covariance should be 1
    #
    K[np.isnan(K)] = 1
    return K
    
    
def rational(x, y, a, M=None, periodic=False):
    """
    Rational covariance
    
        C(x,y) = 1/(1 + |x-y|^2)^a
         
    """
    d = distance(x, y, M, periodic=periodic)
    return (1/(1+d**2))**a   



           
    
class CovKernel(Kernel):
    """
    Integral kernel
    """
    def __init__(self, name=None, parameters=None, dim=1, cov_fn=None):
        """
        Constructor
        
        Inputs:
        
            name: str, name of covariance kernel 
                'constant', 'linear', 'gaussian', 'exponential', 'matern', 
                or 'rational'
            
            parameters: dict, parameter name/value pairs (see functions for
                allowable parameters.
        
        """
        if cov_fn is None:
            assert name is not None, \
                'Covariance should either be specified '\
                ' explicitly or by a string.'
            #
            # Determine covariance kernel
            # 
            if name == 'constant':
                #
                # k(x,y) = sigma
                # 
                cov_fn = constant
            elif name == 'linear':
                #
                # k(x,y) = sigma + <x,My>
                # 
                cov_fn = linear
            elif name == 'gaussian':
                #
                # k(x,y) = sigma*exp(-0.5(|x-y|_M/l)^2)
                # 
                cov_fn = gaussian
            elif name == 'exponential':
                #
                # k(x,y) = sigma*exo(-0.5|x-y|_M/l)
                # 
                cov_fn = exponential
            elif name == 'matern':
                #
                # k(x,y) = 
                # 
                cov_fn = matern
            elif name == 'rational':
                #
                # k(x,y) = 1/(1 + |x-y|^2)^a
                # 
                cov_fn = rational
 
        # Store results
        k = Explicit(f=cov_fn, parameters=parameters, n_variables=2, dim=dim)
        Kernel.__init__(self, f=k)
        

class SPDMatrix(object):
    """
    Symmetric positive definite operator
    """
    def __init__(self, K):
        """
        Constructor
             
        Inputs: 
        
            K: double, (n,n) symmetric positive semidefinite kernel matrix
            
        """
        # Save SPD matrix and mass matrix
        self.__K = K
        
        # Initialize eigendecomoposition
        self.__d = None
        self.__V = None
        
        # Initialize Cholesky decomposition
        self.__L = None
        
    
    def size(self):
        """
        Return the number of rows (=columns) of K
        """
        return self.__K.shape[0]
    
    
    def rank(self):
        """
        Return the rank of the matrix
        """
        if self.issparse():
            return 
        else:
            return np.linalg.matrix_rank(self.__K) 
    
    
    def issparse(self):
        """
        Return True if the matrix is sparse
        """
        return sp.issparse(self.__K)

        
    def get_matrix(self):
        """
        Returns the underlying matrix
        """
        return self.__K
    

    def chol_decomp(self, beta=0):
        """
        Compute the cholesky factorization C = LL', where C=M^{-1}K.
        
        Decompositions are grouped as follows: 
        
        Sparse      cholmod         
        Full        modchol_ldlt    
        
        
        The following quantities are stored:
        
        cholesky (full, non-degenerate): L, such that C = LL'
        
        cholmod (sparse): LDL' = PCP', where
            P: permutation matrix
            L: lower triangular matrix
            D: diagonal matrix
            
        modchol_ldlt (degenerate): factorization  P*(C + E)*P' = L*D*L', where
            P: permutation matrix
            L: cholesky factor (P*L = lower triangular) 
            D: diagonal matrix
            D0: diagonal matrix so that C = L*D0*L'
        
        """
        modified_cholesky = False
        if self.issparse():
            #
            # Sparse matrix
            # 
            try:
                #
                # Try Cholesky (will fail if not PD)
                #
                self.__L = cholesky(self.__K.tocsc(), 
                                    mode='supernodal')
                
                self.__chol_type = 'sparse'
                
            except CholmodNotPositiveDefiniteError:
                modified_cholesky = True
        else:
            #
            # Full Matrix 
            # 
            modified_cholesky = True
                
        if modified_cholesky:
            #
            # Use modified Cholesky
            # 
            if self.issparse():
                #
                # Sparse matrix - convert to full first :(
                # 
                L, D, P, D0 = modchol_ldlt(self.__K.toarray())
            else:
                #
                # Full matrix
                # 
                L, D, P, D0 = modchol_ldlt(self.__K)
            # 
            # Store Cholesky decomposition
            #  
            self.__L = L
            self.__D = D
            self.__P = P 
            self.__D0 = D0
            self.__chol_type = 'full'
                
        
    def chol_type(self):
        """
        Returns the type of Cholesky decomposition 
        (sparse_cholesky/full_cholesky)
        """
        return self.__chol_type


    def get_chol_decomp(self):
        """
        Returns the Cholesky decomposition of the matrix M^{-1}K
        """
        if self.chol_type()=='sparse':
            return self.__L
        elif self.chol_type()=='full':
            return self.__L, self.__D, self.__P, self.__D0 
        
    
    def chol_reconstruct(self):
        """
        Reconstructs the (modified) matrix K
        """
        
        if self.issparse():
            n = self.size()
            #
            # Sparse
            # 
            f = self.get_chol_decomp()

            # Build permutation matrix
            P = f.P()
            I = sp.diags([1],0, shape=(n,n), format='csc')
            PP = I[P,:]
            
            # Compute P'L
            L = f.L()
            L = PP.T.dot(L)
            
            # Check reconstruction LL' = PAP'
            return L.dot(L.T) 
        else:
            #
            # Full matrix
            # 
            L, D = self.__L, self.__D
            return L.dot(D.dot(L.T))
            
    
    def chol_solve(self, b):
        """
        Solve the system C*x = b  by successively solving 
        Ly = b for y and hence L^T x = y for x.
        
        
        Input:
        
            b: double, (n,m) array
        """
        if self.chol_type() == 'sparse':
            #
            # Use CHOLMOD
            #
            return self.__L(b)
        else:
            #
            # Use Modified Cholesky
            # 
            L, D, P, dummy = self.get_chol_decomp()
            PL = P.dot(L)
            y = linalg.solve_triangular(PL,P.dot(b),lower=True, unit_diagonal=True)
            Dinv = sp.diags(1./np.diagonal(D))
            z = Dinv.dot(y)
            x = linalg.solve_triangular(PL.T,z,lower=False,unit_diagonal=True)
            return P.T.dot(x)
        
        
    
    def chol_sqrt(self, b, transpose=False):
        """
        Returns R*b, where A = R*R'
        
            Inputs: 
            
                b: double, compatible vector/matrix
                
                    
            Output:
            
                y: double, array R*b
                
        """
        assert self.__L is not None, \
            'Cholesky factor not computed.'\
            
        n = self.size()
        if self.chol_type()=='sparse':
            #
            # Sparse matrix, use CHOLMOD
            #

            # Build permutation matrix
            P = self.__L.P()
            I = sp.diags([1],0, shape=(n,n), format='csc')
            PP = I[P,:]
                    
            # Compute P'L
            L = self.__L.L()
            R = PP.T.dot(L)
            
            if transpose:
                #
                # R'*b
                # 
                return R.T.dot(b)
            else:
                #
                # R*b
                # 
                return R.dot(b)
        
        elif self.chol_type()=='full':
            #
            # Cholesky Factor stored as full matrix
            # 
            L,D = self.__L, self.__D
            sqrtD = sp.diags(np.sqrt(np.diagonal(D)))
            if transpose:
                #
                # R'b
                # 
                return sqrtD.dot(L.T.dot(b))
            else:
                #
                # Rb
                # 
                return L.dot(sqrtD.dot(b))
        

    def chol_sqrt_solve(self, b, transpose=False):
        """
        Return the solution x of Rx = b, where C = RR'
        
        Note: The 'L' in CHOLMOD's solve_L 
            is the one appearing in the factorization LDL' = PQP'. 
            We first rewrite it as Q = WW', where W = P'*L*sqrt(D)*P
        """
        if self.chol_type() == 'sparse':
            #
            # Sparse Matrix
            #
            f = self.__L
            sqrtDinv = sp.diags(1/np.sqrt(f.D()))
            if transpose:
                # Solve R' x = b
                return f.apply_Pt(f.solve_Lt(sqrtDinv.dot(b)))
            else:
                # Solve Rx = b 
                return sqrtDinv.dot(f.solve_L(f.apply_P(b)))
        else:
            #
            # Full Matrix
            # 
            L, D, P = self.__L, self.__D, self.__P
            PL = P.dot(L)
            sqrtDinv = sp.diags(1/np.sqrt(np.diagonal(D)))
            unit_diagonal = np.allclose(np.diagonal(PL),1)
            if transpose:
                #
                # Solve R' x = b
                # 
                y = sqrtDinv.dot(b)
                
                x = linalg.solve_triangular(PL.T,y, lower=False, 
                                             unit_diagonal=unit_diagonal)
                return P.T.dot(x)
            else:
                y = linalg.solve_triangular(PL, P.dot(b), lower=True, 
                                            unit_diagonal=unit_diagonal)
                
                return sqrtDinv.dot(y)
                
    
    def eig_decomp(self):
        """
        Compute the singular value decomposition USV' of M^{-1}K
        """ 
        K = self.__K
        if self.issparse():
            K = K.toarray()
            
        # Compute eigendecomposition
        d, V = linalg.eigh(K)
        
        # Modify negative eigenvalues
        eps = np.finfo(float).eps
        delta = np.sqrt(eps)*linalg.norm(K, 'fro')
        d[d<=delta] = delta
        
        # Store eigendecomposition
        self.__V = V
        self.__d = d
    
    
    def eig_reconstruct(self):
        """
        Reconstruct the (modified) matrix from its eigendecomposition
        """
        d, V = self.get_eig_decomp()
        return V.dot(np.diag(d).dot(V.T))
    
    
    def get_eig_decomp(self):
        """
        Returns the matrix's eigenvalues and vectors
        """
        # Check that eigendecomposition has been computed
        assert self.__d is not None, \
        'First compute eigendecomposition using "eig_decomp".'
        
        return self.__d, self.__V
        
       
    def eig_solve(self,b):
        """
        Solve the linear system Kx = Mb by means of eigenvalue decomposition, 
        i.e. x = V'Dinv*V*b 
        
        Inputs:
        
            b: double, (n,m) array
        """
        # Check that eigendecomposition has been computed
        assert self.__d is not None, \
        'First compute eigendecomposition using "eig_decomp".'
        
        V = self.__V  # eigenvectors
        d = self.__d  # eigenvalues
        D_inv = diagonal_inverse(d)
        return V.dot(D_inv.dot(np.dot(V.T, b)))
            
    
    def eig_sqrt(self, x, transpose=False):
        """
        Compute Rx (or R'x), where A = RR'
        
        Inputs:
        
            x: double, (n,k) array
            
            transpose: bool, determine whether to compute Rx or R'x
            
        
        Output:
        
            b = Rx/R'x
        """
        d, V = self.__d, self.__V
        if transpose:
            # Sqrt(D)*V'x
            return np.diag(np.sqrt(d)).dot(V.T.dot(x))
        else:
            # V*Sqrt(D)*x
            return V.dot(np.diag(np.sqrt(d)).dot(x))
    
    
    def eig_sqrt_solve(self, b, transpose=False):
        """
        Solve the system Rx=b (or R'x=b if transpose) where R = V*sqrt(D) in 
        the decomposition M^{-1}K = VDV' = RR' 
        
        Inputs:
        
            b: double, (n,k)  right hand side
            
            transpose: bool [False], specifies whether system or transpose is 
                to be solved.
        """
        V = self.__V  # eigenvectors
        d = self.__d  # eigenvalues
        sqrtD_inv = diagonal_inverse(np.sqrt(d))
        if transpose:
            #
            # Solve sqrtD*V'x = b
            # 
            return V.dot(sqrtD_inv.dot(b))
        else:
            #
            # Solve V*sqrtD x = b
            #
            return sqrtD_inv.dot(np.dot(V.T, b))
        
    
class Covariance(SPDMatrix):
    """
    Covariance operator
    """
    def __init__(self, cov_kernel, dofhandler, 
                 subforest_flag=None, method='interpolation'):
        """
        Constructor
        """
        # Store covariance kernel
        assert isinstance(cov_kernel, Kernel), \
        'Input "cov_kernel" should be a Kernel object.'
        
        self.__kernel = cov_kernel
        
        # Store dofhandler
        dofhandler.distribute_dofs(subforest_flag=subforest_flag)
        dofhandler.set_dof_vertices()
        self.__dofhandler = dofhandler
        
        # Mesh 
        mesh = dofhandler.mesh
        
        # Basis
        u = Basis(dofhandler, 'u')
        
        # Mass matrix 
        m = Form(trial=u, test=u)
        
        if method=='interpolation':
            #
            # Construct integral kernel from interpolants
            #    
            c = IIForm(kernel=cov_kernel, test=u, trial=u)
            assembler = Assembler([[c]], mesh, subforest_flag=subforest_flag)
            assembler.assemble()
            
            K = assembler.af[0]['bilinear'].get_matrix().toarray()
        elif method=='projection':
            #
            # Simple assembler for the mass matrix
            # 
            c = IPForm(kernel=cov_kernel, test=u, trial=u)
            assembler = Assembler([[m],[c]], mesh, subforest_flag=subforest_flag)
            assembler.assemble()
            
            C = assembler.af[1]['bilinear'].get_matrix().tocsc()
            M = assembler.af[0]['bilinear'].get_matrix().tocsc()
            
            K = spla.spsolve(M,C).toarray() 
        else:
            raise Exception('Only "interpolation", "projection",'+\
                            ' or "nystroem" supported for input "method"')
        
        self.__K = K
        self.__method = method
        self.__assembler = assembler
        self.__subforest_flag = subforest_flag
    
        # 
        # Initialize decompositions
        #
        
        # SVD 
        self.__svd_S = None  # singular values
        self.__svd_U = None  # singular vectors
        
        # Cholesky
        self.__schol_L = None  # sparse cholesky factor
        self.__chol_L  = None  # full cholesky factor 
        self.__chol_mD = None  # full modified block diagonal matrix >0
        self.__chol_P  = None  # full permutation matrix
        self.__chol_D  = None  # full unmodified block diagonal matrix >=0
        
        
    def assembler(self):
        """
        Returns the assemler
        """
        return self.__assembler
    
    
    def dim(self):
        """
        Returns the dimension of the underlying domain
        """
        return self.dofhandler.mesh.dim()
    
    
    def size(self):
        """
        Returns the size of the covariance matrix
        """
        return self.cov().shape[0]
    
    
    def rank(self):
        """
        Returns the rank of the covariance matrix
        """
        s = self.__svd_S
        if s is not None: 
            eps = np.finfo(float).eps
            rank = np.sum(s>np.sqrt(eps))
            return rank
        
        
    
        
    def kernel(self):
        """
        Returns the covariance kernel
        """
        return self.__kernel     
        
        
    def cov(self):
        """
        Return the covariance matrix
        """
        return self.__K
           
    
    def discretization_type(self):
        """
        Returns the assembly/approximation method ('interpolation' or 'projection')
        """
        return self.__method
   
        
    def iid_gauss(self, n_samples=1):
        """
        Returns a matrix whose columns are N(0,I) vectors of length n 
        """
        return np.random.normal(size=(self.size(),n_samples)) 
    
    
    def sample(self, Z=None, n_samples=1):
        """
        Generate a random sample from a N(0,C), where C = M^{-1}S    
        """
        if Z is not None:
            assert Z.shape[0]==self.size(), 'Incompatible shape' 
        else:
            Z = self.iid_gauss(n_samples=n_samples)
        
        S, V = self.eigenvalues(), self.eigenvectors()
        U = V.dot( np.diag(np.sqrt(S)).dot(Z))
        
        return U    
    
    
    def condition(self, A, Ko=0):
        """
        Computes the conditional covariance of X, given E ~ N(AX, Ko). 
        
        Inputs:
        
            A: double, (k,n) 
            
            Ko: double symm, covariance matrix of E.
        """
        pass
         
'''   
class Covariance(object):
    """
    Covariance kernel for Gaussian random fields
    """        
    
    
            
    def __init__(self, name, parameters, mesh, element, n_gauss=9, 
                 assembly_type='projection', subforest_flag=None, lumped=False):
        """
        Construct a covariance matrix from the specified covariance kernel
        
        Inputs: 
        
            
            
            mesh: Mesh, object denoting physical mesh
            
            etype: str, finite element space (see Element for
                supported spaces).
                
            assembly_type: str, specifies type of approximation,
                projection, or collocation
                
            

        """
        
        self.__kernel = CovKernel(name, parameters)
        assert isinstance(element, Element), \
        'Input "element" must be of type Element.'
            
        dofhandler = DofHandler(mesh, element)
        dofhandler.distribute_dofs()
        
        if assembly_type=='projection':
            #
            # Approximate covariance kernel by its projection
            #
            self.assemble_projection()
        elif assembly_type=='collocation':
            #
            # Approximate covariance kernel by collocation
            #
            self.assemble_collocation() 
        else:
            raise Exception('Use "projection" or "collocation" for'+\
                            ' input "assembly_type"')
        

    def assemble_projection(self):
        """
        Compute the discretization (C,M) of the covariance operator
        
        Ku(x) = I_D c(x,y) u(y) dy
        
        within a finite element projection framework. In particular, 
        compute the matrix pair (C,M), where 
        
            C = ((c(.,.)phi_i(x), phi_j(y))
            
            M = (phi_i(x), phi_j(x))
            
            So that K ~ M^{-1}C.
            
            
        Inputs:
        
            kernel: bivariate function, c(x,y, pars)
            
        """
        mesh = self.mesh
        subforest_flag = self.subforest_flag
        #
        # Iterate over outer integral
        # 
        for cell01 in mesh.cells.get_leaves(subforest_flag=subforest_flag):
            #
            # Iterate over inner integral
            # 
            for cell02 in mesh.cells.get_leaves(subforest_flag=subforest_flag):
                pass
    
          #
            # Assemble double integral
            #
            #  C(pi,pj) = II pi(xi) pj(xj) cov(xi,xj) dx 
            
            # Initialize 
            n_dofs = dofhandler.n_dofs()
            Sigma = np.zeros((n_dofs,n_dofs))
            m_row = []
            m_col = []
            m_val = []
            
            # Gauss rule on reference domain
            rule = GaussRule(9, element=element)
            xg_ref = rule.nodes()
            w_xg_ref = rule.weights()
            n_gauss = rule.n_nodes()
            
            # Iterate over mesh nodes: outer loop
            leaves = mesh.root_node().get_leaves()
            n_nodes = len(leaves)
            for i in range(n_nodes):
                # Local Gauss nodes and weights
                xnode = leaves[i]
                xcell = xnode.cell()
                xdofs = dofhandler.get_global_dofs(xnode)
                n_dofs_loc = len(xdofs)
                xg = xcell.map(xg_ref) 
                w_xg = rule.jacobian(xcell)*w_xg_ref
                
                # Evaluate shape functions and local mass matrix 
                xphi = element.shape(xg_ref)
                w_xphi = np.diag(w_xg).dot(xphi)
                m_loc = np.dot(xphi.T, np.dot(w_xphi))
                
                # Iterate over mesh nodes: inner loop
                for j in range(i,n_nodes):
                    ynode = leaves[j]
                    ycell = ynode.cell()
                    ydofs = dofhandler.get_global_dofs(ynode)
                    yg = xcell.map(xg_ref)
                    w_yg = rule.jacobian(ycell)*w_xg_ref
                    if i == j: 
                        yphi = xphi
                    else:
                        yphi = element.shape(xg_ref)
                    w_yphi = np.diag(w_yg).dot(yphi)
                    
                #
                # Evaluate covariance function at the local Gauss points
                # 
                ii,jj = np.meshgrid(np.arange(n_gauss),np.arange(n_gauss))
                if mesh.dim == 1:
                    x1, x2 = xg[ii.ravel()], yg[jj.ravel()]
                elif mesh.dim == 2:
                    x1, x2 = xg[ii.ravel(),:],yg[jj.ravel(),:]
                    
                C_loc = cov_fn(x1,x2,**cov_par).reshape(n_gauss,n_gauss)
                CC_loc = np.dot(w_yphi.T,C_loc.dot(w_xphi))
                    
            # Local to global mapping     
            for ii in range(n_dofs_loc):
                for jj in range(n_dofs_loc):
                    # Covariance 
                    Sigma[xdofs[ii],ydofs[jj]] += CC_loc[i,j]
                    Sigma[ydofs[jj],xdofs[ii]] += CC_loc[i,j]
                    
                    # Mass Matrix
                    m_row.append(ii)
                    m_col.append(jj)
                    m_val.append(m_loc[i,j])
                    
            
            # Define global mass matrix
            M = sp.coo_matrix((m_val,(m_row,m_col)))
            
            if lumped: 
                M_lumped = np.array(M.tocsr().sum(axis=1)).squeeze()
                #
                # Adjust covariance
                #
                Sigma = sp.diags(1/M_lumped)*Sigma
                return Sigma
            else:
                return Sigma, M
            
    
    
    def assemble_collocation(self):
        """
        Compute the discretization C of the covariance operator
        
        Ku(x) = I_D c(x,y) u(y) dy
        
        by collocation.
        
        Inputs:
        
            kernel
            
            pars
            
        
        Outputs:
            
            None
            
        
        Internal:
        
            self.__C
            
        """
        #
        # Interpolate the kernel at Dof-Vertices 
        # 
        
        
        u = Basis(element, 'u')
        
        assembler = Assembler()
        #
        # Assemble by finite differences
        # 
        dim = mesh.dim()
        element = QuadFE(dim, 'Q1')
        dofhandler = DofHandler(mesh, element)
        dofhandler.distribute_dofs()
        x = dofhandler.dof_vertices()
        n = dofhandler.n_dofs()
        Sigma = np.empty((n,n))
        i,j = np.triu_indices(n)
        if dim == 1:
            Sigma[i,j] = cov_fn(x[i],x[j], **cov_par, \
                                periodic=periodic, M=M)
        if dim == 2:
            Sigma[i,j] = cov_fn(x[i,:],x[j,:], **cov_par, \
                                periodic=periodic, M=M)
        #
        # Reflect upper triangular part onto lower triangular part
        # 
        i,j = np.tril_indices(n,-1)
        Sigma[i,j] = Sigma[j,i]
        return Sigma      
'''
  
    
class Precision(object):
    """
    Precision Matrix for 
    """
    pass
    
    def __init__(self, Q):
        """
        Constructor
        """
        self.__Q = Q

        self.__chol = cholesky(Q)
        
        
    def matrix(self):
        """
        Returns precision matrix
        """
        return self.__Q

    
    
    def L(self, b=None):
        """
        Return lower triangular Cholesky factor L or compute L*b
        
            Inputs: 
            
                b: double, compatible vector
                    
                    
            Output:
            
                L: double, (sparse) lower triangular left Cholesky 
                    factor (if no b is specified) 
                    
                    or 
                
                y = L*b: double, vector.
                
        """
        #
        # Precision Matrix
        # 
        assert self.__f_prec is not None, \
            'Precision matrix not specified.'
        if sp.isspmatrix(self.__Q):
            #
            # Sparse matrix, use CHOLMOD
            #  
            P = self.matrix().P()
            L = self.matrix().L()[P,:][:,P]
        else:
            #
            # Cholesky Factor stored as full matrix
            # 
            L = self.__f_prec

        #
        # Parse b   
        # 
        if b is None:
            return L 
        else: 
            return L.dot(b) 
    
    
    
    def solve(self, b):
        """
        Return the solution x of Qx = b by successively solving 
        Ly = b for y and hence L^T x = y for x.
        
        """
        if sp.isspmatrix(self.matrix()):
            return self.__f_prec(b)
        else:
            y = np.linalg.solve(self.__f_prec, b)
            return np.linalg.solve(self.__f_prec.transpose(),y)
    
    
    
    def L_solve(self, b, mode='precision'):
        """
        Return the solution x of Lx = b, where Q = LL' (or S=LL')
        
        Note: The 'L' CHOLMOD's solve_L is the one appearing in the 
            factorization LDL' = PQP'. We first rewrite it as 
            Q = WW', where W = P'*L*sqrt(D)*P
        """
        assert self.mode_supported(mode),\
            'Mode "'+ mode + '" not supported for this random field.'
        if mode == 'precision':
            if sp.isspmatrix(self.__Q):
                # Sparse
                f = self.__f_prec
                sqrtDinv = sp.diags(1/np.sqrt(f.D()))
                return f.apply_Pt(sqrtDinv*f.solve_L(f.apply_P(b))) 
            else: 
                # Full
                return np.linalg.solve(self.__f_prec,b)
        elif mode == 'covariance':
            if sp.isspmatrix(self.__Sigma):
                # Sparse
                f = self.__f_cov
                sqrtDinv = sp.diags(1/np.sqrt(f.D()))
                return f.apply_Pt(sqrtDinv*f.solve_L(f.apply_P(b)))
            else:
                # Full
                return np.linalg.solve(self.__f_cov,b)
            
    
    def Lt_solve(self, b):
        """
        Return the solution x, of L'x = b, where Q = LL'
        
        Note: The 'L' CHOLMOD's solve_L is the one appearing in the 
            factorization LDL' = PQP'. We first rewrite it as 
            Q = WW', where W' = P'*sqrt(D)*L'*P.
        """
         
        if sp.isspmatrix(self.matrix()):
            # Sparse
            f = self.__f_prec
            sqrtDinv = sp.diags(1/np.sqrt(f.D()))
            return f.apply_Pt(f.solve_Lt(sqrtDinv*(f.apply_P(b))))
        else:
            # Full
            return np.linalg.solve(self.__f_prec.transpose(),b)
        


class MaternPrecision(Precision):
    """
    Precision matrix related to the Matern precision.
    """
    def __init__(self):
        """
        Constructor
        """
        pass
    
    
    
# =============================================================================
# Gaussian Markov Random Field Class
# =============================================================================
class Gmrf(object):
    """
    Gaussian Markov Random Field
    
    Inputs (or important information) may be: 
        covariance/precision
        sparse/full
        full rank/degenerate
        finite difference / finite element
                   
    Modes:  
        
        Cholesky:
            Exploits sparsity
            
        
        Singular value decomposition (KL)
            Computationally expensive
            Conditioning is easy
            
    Wishlist: 
    
        - Estimate the precision matrix from the covariance (Quic)
        - Log likelihood evaluation
        
               
    NOTES: 
    
    TODO: In what format should the sparse matrices be stored? consistency 
    TODO: Check: For sparse matrix A, Ax is computed by A.dot(x), not np.dot(A,x) 
    
    """
    @staticmethod
    def matern_precision(mesh, element, alpha, kappa, tau=None, 
                         boundary_conditions=None):
        """
        Return the precision matrix for the Matern random field defined on the 
        spatial mesh. The field X satisfies
        
            (k^2 - div[T(x)grad(.)])^{a/2} X = W
        
        Inputs: 
        
            mesh: Mesh, finite element mesh on which the field is defined
            
            element: QuadFE, finite element space of piecewise polynomials
            
            alpha: int, positive integer (doubles not yet implemented).
            
            kappa: double, positive regularization parameter.
            
            tau: (Axx,Axy,Ayy) symmetric tensor or diffusion coefficient function.
            
            boundary_conditions: tuple of boundary locator function and boundary value
                function (viz. fem.Assembler)
            
            
        Outputs:
        
            Q: sparse matrix, in CSC format
            
        """
        system = Assembler(mesh, element)
        
        #
        # Assemble (kappa * M + K)
        #
        bf = [(kappa,'u','v')]
        if tau is not None:
            #
            # Test whether tau is a symmetric tensor
            # 
            if type(tau) is tuple:
                assert len(tau)==3, 'Symmetric tensor should have length 3.'
                axx,axy,ayy = tau
                bf += [(axx,'ux','vx'),(axy,'uy','vx'),
                       (axy,'ux','vy'),(ayy,'uy','vy')]
            else:
                assert callable(tau) or isinstance(tau, Number)
                bf += [(tau,'ux','vx'),(tau,'uy','vy')]
        else:
            bf += [(1,'ux','vx'),(1,'uy','vy')]
        G = system.assemble(bilinear_forms=bf, 
                            boundary_conditions=boundary_conditions)
        G = G.tocsr()
        
        #
        # Lumped mass matrix
        # 
        M = system.assemble(bilinear_forms=[(1,'u','v')]).tocsr()
        m_lumped = np.array(M.sum(axis=1)).squeeze()
        
            
        if np.mod(alpha,2) == 0:
            #
            # Even power alpha
            # 
            Q = cholesky(G.tocsc())
            count = 1
        else:
            #
            # Odd power alpha
            # 
            Q = cholesky_AAt((G*sp.diags(1/np.sqrt(m_lumped))).tocsc())
            count = 2
        
        while count < alpha:
            #
            # Update Q
            #
            Q = cholesky_AAt((G*sp.diags(1/m_lumped)*Q.apply_Pt(Q.L())).tocsc()) 
            count += 2
        
        return Q
 
 
    def __init__(self, mean=None, precision=None, covariance=None):
        """
        Constructor
        
        Inputs:
        
            mesh: Mesh, Computational mesh
        
            mu: Function, random field expectation (default=0)
            
            precision: double, (n,n) sparse/full precision matrix
                    
            covariance: double, (n,n) sparse/full covariance matrix
                    
            element: QuadFE, finite element
                
            
        Attributes:
        
            __Q: double, precision matrix
            
            __Sigma: double, covariance matrix
            
            __mu: double, expected value
            
            __b: double, Q\mu (useful for sampling)
            
            __f_prec: double, lower triangular left cholesky factor of precision
                If Q is sparse, then use CHOLMOD.
                
            __f_cov: double, lower triangular left cholesky factor of covariance
                If Sigma is sparse, we use CHOLMOD.
                
            __dim: int, effective dimension
            
                
            mesh: Mesh, Quadtree mesh
            
            element: QuadFE, finite element    
            
            discretization: str, 'finite_elements', or 'finite_differences' 
            
        """   
        n = None
        #
        # Need at least one
        #
        if covariance is not None:
            assert isinstance(covariance, Covariance), 'Input "covariance" '+\
                'must be a "Covariance" object.'
                
            self.__covariance = covariance
        
        if precision is None and covariance is None:
            raise Exception('Specify precision or covariance (or both).')  
        #
        # Precision matrix
        # 
        
        Q = None
        if precision is not None:    
            if sp.isspmatrix(precision):
                #
                # Precision is sparse matrix
                # 
                n = precision.shape[0]
                Q = precision
                self.__f_prec = cholesky(Q.tocsc())
                #
                # Precision is cholesky factor
                # 
            elif type(precision) is Factor:
                n = len(precision.P())
                Q = (precision.L()*precision.L().transpose())
                self.__f_prec = precision
            else:
                #
                # Precision is full matrix
                #
                n = precision.shape[0]
                Q = precision 
                self.__f_prec = np.linalg.cholesky(precision)
        self.__Q = Q
        #
        # Covariance matrix
        # 
        self.__Sigma = covariance
        if covariance is not None:
            n = covariance.shape[0]
            if sp.isspmatrix(covariance):
                try:
                    self.__f_cov = cholesky(covariance.tocsc())
                except np.linalg.linalg.LinAlgError:
                    print('It seems a linalg error occured') 
            else:
                # Most likely
                try:
                    self.__f_cov = np.linalg.cholesky(covariance)
                except np.linalg.linalg.LinAlgError as ex:
                    if ex.__str__() == 'Matrix is not positive definite':
                        #
                        # Rank deficient covariance
                        # 
                        # TODO: Pivoted Cholesky
                        self.__f_cov = None
                        self.__svd = np.linalg.svd(covariance)  
                    else:
                        raise Exception('I give up.')
        #
        # Check compatibility
        # 
        if covariance is not None and precision is not None:
            n_cov = covariance.shape[0]
            n_prc = precision.shape[0]
            assert n_prc == n_cov, \
                'Incompatibly shaped precision and covariance.'
            isI = precision.dot(covariance)
            if sp.isspmatrix(isI):
                isI = isI.toarray()
                assert np.allclose(isI, np.eye(n_prc),rtol=1e-10),\
               'Covariance and precision are not inverses.' 
        #
        # Mean
        # 
        if mean is not None:
            assert len(mean) == n, 'Mean incompatible with precision/covariance.'
        else: 
            mu = np.zeros(n)
        self.__mu = mu
        # 
        # b = Q\mu
        # 
        if not np.allclose(mu, np.zeros(n), 1e-10):
            # mu is not zero
            b = self.Q_solve(mu)
        else:
            b = np.zeros(n)
        self.__b = b
        #
        # Store size of matrix
        # 
        self.__n = n    
        
        
    @classmethod
    def from_covariance_kernel(cls, cov_name, cov_par, mesh, \
                               mu=None, element=None):
        """
        Initialize Gmrf from covariance function
        
        Inputs: 
        
            cov_name: string, name of one of the positive definite covariance
                functions that are supported 
                
                    ['constant', 'linear', 'sqr_exponential', 'exponential', 
                     'matern', 'rational'].
                     
            cov_par: dict, parameter name value pairs
            
            mesh: Mesh, computational mesh
            
            mu: double, expectation vector
            
            element: QuadFE, element (necessary for finite element discretization).
             
                     
        Note: In the case of finite element discretization, mass lumping is used. 
        """
        # Convert covariance name to function 
        #cov_fn = globals()['Gmrf.'+cov_name+'_cov']
        cov_fn = locals()[cov_name+'_cov']
        #
        # Discretize the covariance function
        # 
        if element is None:
            #
            # Pointwise evaluation of the kernel
            #
            x = mesh.quadvertices()
            n_verts = x.shape[0]
            Y = np.repeat(x, n_verts, axis=0)
            X = np.tile(x, (n_verts,1))
            Sigma = cov_fn(X,Y,**cov_par).reshape(n_verts,n_verts)
            discretization = 'finite_differences' 
        else:
            #
            # Finite element discretization of the kernel
            # 
            discretization = 'finite_elements'
            #
            # Assemble double integral
            #

            system = Assembler(mesh, element) 
            n_dofs = system.n_dofs()
            Sigma = np.zeros((n_dofs,n_dofs))
            
            # Gauss points
            rule = system.cell_rule()
            n_gauss = rule.n_nodes()                  
            for node_1 in mesh.root_node().get_leaves():
                node_dofs_1 = system.get_global_dofs(node_1)
                n_dofs_1 = len(node_dofs_1)
                cell_1 = node_1.cell()
                
                
                weights_1 = rule.jacobian(cell_1)*rule.weights()
                x_gauss_1 = rule.map(cell_1, x=rule.nodes())
                phi_1 = system.shape_eval(cell=cell_1)    
                WPhi_1 = np.diag(weights_1).dot(phi_1)
                for node_2 in mesh.root_node().get_leaves():
                    node_dofs_2 = system.get_global_dofs(node_2)
                    n_dofs_2 = len(node_dofs_2)
                    cell_2 = node_2.cell()
                    
                    x_gauss_2 = rule.map(cell_2, x=rule.nodes())
                    weights_2 = rule.jacobian(cell_2)*rule.weights()
                    phi_2 = system.shape_eval(cell=cell_2)
                    WPhi_2 = np.diag(weights_2).dot(phi_2)
                    
                    i,j = np.meshgrid(np.arange(n_gauss),np.arange(n_gauss))
                    x1, x2 = x_gauss_1[i.ravel(),:],x_gauss_2[j.ravel(),:]
                    C_loc = cov_fn(x1,x2,**cov_par).reshape(n_gauss,n_gauss)
                
                    CC_loc = np.dot(WPhi_2.T,C_loc.dot(WPhi_1))
                    for i in range(n_dofs_1):
                        for j in range(n_dofs_2):
                            Sigma[node_dofs_1[i],node_dofs_2[j]] += CC_loc[i,j]
                        
                        
            
            #
            # Lumped mass matrix (not necessary!)
            #
            M = system.assemble(bilinear_forms=[(1,'u','v')]).tocsr()
            m_lumped = np.array(M.sum(axis=1)).squeeze()
            #
            # Adjust covariance
            #
            Sigma = sp.diags(1/m_lumped).dot(Sigma)
            
        return cls(mu=mu, covariance=Sigma, mesh=mesh, element=element, \
                   discretization=discretization)
    
    @classmethod
    def from_matern_pde(cls, alpha, kappa, mesh, element=None, tau=None):
        """
        Initialize finite element Gmrf from matern PDE
        
        Inputs: 
        
            alpha: double >0, smoothness parameter
            
            kappa: double >0, regularization parameter
            
            mesh: Mesh, computational mesh 
            
            *element: QuadFE, finite element (optional)
            
            *tau: double, matrix-valued function representing the structure
                tensor tau(x,y) = [uxx uxy; uxy uyy].
        """
        #if element is not None: 
        #    discretization = 'finite_elements'
        #else:
        #    discretization = 'finite_differences'
            
        Q = Gmrf.matern_precision(mesh, element, alpha, kappa, tau)
        return cls(precision=Q, mesh=mesh, element=element)
    
    
    
    
    
    def Q(self):
        """
        Return the precision matrix
        """
        return self.__Q
    
    
    def Sigma(self):
        """
        Return the covariance matrix
        """
        return self.__Sigma
        
    
    def L(self, b=None, mode='precision'):
        """
        Return lower triangular Cholesky factor L or compute L*b
        
            Inputs: 
            
                b: double, compatible vector
                
                mode: string, Specify the matrix for which to return the 
                    Cholesky factor: 'precision' (default) or 'covariance'
                    
                    
            Output:
            
                Lprec/Lcov: double, (sparse) lower triangular left Cholesky 
                    factor (if no b is specified) 
                    
                    or 
                
                y = Lprec*b / y = Lcov*b: double, vector.
                
        TODO: Move to Precision/Covariance
        """
        #
        # Parse mode
        #
        assert self.mode_supported(mode), \
            'Mode "'+mode+'" not supported by this random field.' 
        if mode == 'precision':
            #
            # Precision Matrix
            # 
            assert self.__f_prec is not None, \
                'Precision matrix not specified.'
            if sp.isspmatrix(self.__Q):
                #
                # Sparse matrix, use CHOLMOD
                #  
                P = self.__f_prec.P()
                L = self.__f_prec.L()[P,:][:,P]
            else:
                #
                # Cholesky Factor stored as full matrix
                # 
                L = self.__f_prec

        elif mode == 'covariance':
            #
            # Covariance Matrix
            # 
            assert self.__f_cov is not None, \
                'Covariance matrix not specified.'
            if sp.isspmatrix(self.__Sigma):
                #
                # Sparse Covariance matrix, use CHOLMOD
                # 
                P = self.__f_cov.P()
                L = self.__f_cov.L()[P,:][:,P]
            else:
                #
                # Cholesky Factor stored as full matrix
                # 
                L = self.__f_cov
        else:
            raise Exception('Mode not recognized. Use either' + \
                            '"precision" or "covariance".')
        #
        # Parse b   
        # 
        if b is None:
            return L 
        else: 
            return L.dot(b) 
        
        
    def mu(self,n_copies=None):
        """
        Return the mean of the random vector
        
        Inputs:
        
            n_copies: int, number of copies of the mean
            
        Output: 
        
            mu: (n,n_copies) mean
        """
        if n_copies is not None:
            assert type(n_copies) is np.int, \
                'Number of copies should be an integer.'
            if n_copies == 1:
                return self.__mu
            else:
                return np.tile(self.__mu, (n_copies,1)).transpose()
        else:
            return self.__mu
        
    
    def b(self):
        """
        Return Q\mu
        """
        return self.__b
    
    
    def n(self):
        """
        Return the dimension of the random vector 
        """
        return self.__n
    
    
    def rank(self):
        """
        Return the rank of the covariance/precision matrix
        
        Note: If the matrix is degenerate, we must use the covariance's
            or precision's eigendecomposition.
        """
        pass
    
    
    def Q_solve(self, b):
        """
        Return the solution x of Qx = b by successively solving 
        Ly = b for y and hence L^T x = y for x.
        
        TODO: Move to precision
        """
        if sp.isspmatrix(self.__Q):
            return self.__f_prec(b)
        else:
            y = np.linalg.solve(self.__f_prec, b)
            return np.linalg.solve(self.__f_prec.transpose(),y)
    
    
    
    def L_solve(self, b, mode='precision'):
        """
        Return the solution x of Lx = b, where Q = LL' (or S=LL')
        
        Note: The 'L' CHOLMOD's solve_L is the one appearing in the 
            factorization LDL' = PQP'. We first rewrite it as 
            Q = WW', where W = P'*L*sqrt(D)*P
        """
        assert self.mode_supported(mode),\
            'Mode "'+ mode + '" not supported for this random field.'
        if mode == 'precision':
            if sp.isspmatrix(self.__Q):
                # Sparse
                f = self.__f_prec
                sqrtDinv = sp.diags(1/np.sqrt(f.D()))
                return f.apply_Pt(sqrtDinv*f.solve_L(f.apply_P(b))) 
            else: 
                # Full
                return np.linalg.solve(self.__f_prec,b)
        elif mode == 'covariance':
            if sp.isspmatrix(self.__Sigma):
                # Sparse
                f = self.__f_cov
                sqrtDinv = sp.diags(1/np.sqrt(f.D()))
                return f.apply_Pt(sqrtDinv*f.solve_L(f.apply_P(b)))
            else:
                # Full
                return np.linalg.solve(self.__f_cov,b)
    
    
    def Lt_solve(self, b, mode='precision'):
        """
        Return the solution x, of L'x = b, where Q = LL' (or S=LL')
        
        Note: The 'L' CHOLMOD's solve_L is the one appearing in the 
            factorization LDL' = PQP'. We first rewrite it as 
            Q = WW', where W' = P'*sqrt(D)*L'*P.
        """
        assert self.mode_supported(mode), \
            'Mode "'+ mode + '" not supported for this random field.'
        if mode == 'precision':
            #
            # Precision matrix
            # 
            if sp.isspmatrix(self.__Q):
                # Sparse
                f = self.__f_prec
                sqrtDinv = sp.diags(1/np.sqrt(f.D()))
                return f.apply_Pt(f.solve_Lt(sqrtDinv*(f.apply_P(b))))
            else:
                # Full
                return np.linalg.solve(self.__f_prec.transpose(),b)
        elif mode == 'covariance':
            #
            # Covariance matrix
            # 
            if sp.isspmatrix(self.__Sigma):
                # Sparse
                f = self.__f_cov
                sqrtDinv = sp.diags(1/np.sqrt(f.D()))
                return f.apply_Pt(f.solve_Lt(sqrtDinv*(f.apply_P(b))))
            else:
                # Full
                return np.linalg.solve(self.__f_cov.transpose(),b)
        else:
            raise Exception('For mode, use "precision" or "covariance".')
    
    
    def KL(self, precision=None, k=None):
        """
        Inputs:
        
        Outputs:
        
        """
        mesh = self.mesh()
        
    
    
    def sample(self, n_samples=None, z=None, mode='precision'):
        """
        Generate sample realizations from Gaussian random field.
        
        Inputs:
        
            n_samples: int, number of samples to generate
            
            z: (n,n_samples) random vector ~N(0,I).
            
            mode: str, specify parameters used to simulate random field
                ['precision', 'covariance', 'canonical']
            
            
        Outputs:
        
            x: (n,n_samples), samples paths of random field
            
                
        Note: Samples generated from the cholesky decomposition of Q are 
            different from those generated from that of Sigma. 
                
                Q = LL' (lower*upper)
                  
            =>  S = Q^(-1) = L'^(-1) L^(-1) (upper*lower) 
        """
        assert self.mode_supported(mode), \
            'Mode "'+ mode + '" not supported for this random field.'
        #
        # Preprocess z   
        # 
        if z is None:
            assert n_samples is not None, \
                'Specify either random array or sample size.'
            z = np.random.normal(size=(self.n(), n_samples))
            z_is_a_vector = False
        else:
            #
            # Extract number of samples from z
            #  
            if len(z.shape) == 1:
                nz = 1
                z_is_a_vector = True
            else:
                nz = z.shape[1]
                z_is_a_vector = False 
            assert n_samples is None or n_samples == nz, \
                'Sample size incompatible with given random array.'
            n_samples = nz
        #
        # Generate centered realizations
        # 
        if mode in ['precision','canonical']:
            v = self.Lt_solve(z, mode='precision')
        elif mode == 'covariance':
            if self.__f_cov is not None:
                v = self.L(z, mode='covariance')
            elif self.__svd is not None:
                U,s,_ = self.__svd
                v = U.dot(np.dot(np.sqrt(np.diag(s)), z))  
        #
        # Add mean
        # 
        if z_is_a_vector:
            return v + self.mu()
        else:
            return v + self.mu(n_samples)
        
    
    def mode_supported(self, mode):
        """
        Determine whether enough information is available to process given mode
        """
        if mode == 'precision':
            return self.__Q is not None
        elif mode == 'covariance':
            return self.__Sigma is not None
        elif mode == 'canonical':
            return self.__Q is not None
        else:
            raise Exception('For modes, use "precision", ' + \
                            '"covariance", or "canonical".')
            
    
    def condition(self, constraint=None, constraint_type='pointwise',
                  mode='precision', output='gmrf', n_samples=1, z=None):
        """
        
        Inputs:
        
            constraint: tuple, parameters specifying the constraint, determined
                by the constraint type:
                
                'pointwise': (dof_indices, constraint_values) 
                
                'hard': (A, b), where A is the (k,n) constraint matrix and 
                    b is the (k,m) array of realizations (usually m is None).
                
                'soft': (A, Q)
        
            constraint_type: str, 'pointwise' (default), 'hard', 'soft'.
            
            mode: str, 'precision' (default), or 'covariance', or 'svd'.
            
            output: str, type of output 'gmrf', 'sample', 'log_pdf' 
            
        Output:
        
            X: Gmrf, conditioned random field. 
            
        TODO: Unfinished
        """
        if constraint_type == 'pointwise':
            i_b, x_b = constraint
            i_a = [i not in i_b for i in range(self.n())]
            mu_a, mu_b = self.mu()[i_a], self.mu()[i_b]
            Q_aa = self.Q().tocsc()[np.ix_(i_a,i_a)]
            Q_ab = self.Q().tocsc()[np.ix_(i_a,i_b)]
            
            #
            # Conditional random field
            # 
            mu_agb = mu_a - spla.spsolve(Q_aa, Q_ab.dot(x_b-mu_b))
            if n_samples is None:
                return Gmrf(mu=mu_agb, precision=Q_aa)
            else: 
                pass
            
        elif constraint_type == 'hard':
            A, e  = constraint
            assert self.mode_supported(mode), 'Mode not supported.'
            if output == 'gmrf':
                if mode == 'precision':
                    pass
                elif mode == 'covariance':
                    mu = self.mu()
                    S  = self.Sigma()
                    c =  A.dot(mu) - e
                    V = S.dot(A.T.dot(linalg.solve(A.dot(S.dot(A.T)),c)))
                    mu_gAx = self.mu() - V 
                     
            elif output == 'sample':
                #
                # Generate samples directly via Kriging
                # 
                if z is None:
                    # Z is not specified -> generate samples
                    z = self.iid_gauss(n_samples)
                if mode == 'precision':
                    #
                    # Use precision matrix
                    #
                    # Sample from unconstrained gmrf
                    v = self.Lt_solve(z)
                    x = self.mu(n_samples) + v
                    
                    # Compute [Sgm*A'*(A*Sgm*A')^(-1)]'
                    V = self.Q_solve(A.T)
                    W = A.dot(V)
                    U = linalg.solve(W, V.T)
                    
                    # Compute x|{Ax=e} = x - Sgm*A'*(A*Sgm*A')^(-1)(Ax-e)
                    if n_samples > 1:
                        e = np.tile(e, (n_samples,1)).transpose()
                    c = A.dot(x)-e
                    return x-np.dot(U.T,c) 
                           
                elif mode == 'covariance':
                    #
                    # Use covariance matrix
                    #
                    x = self.sample(n_samples=n_samples, z=z, 
                                    mode='covariance')
                    if n_samples > 1:
                        e = np.tile(e, (n_samples,1)).transpose()
                    c = A.dot(x)-e
                    
                    # Compute Sgm*A'*(A*Sgm*A')^(-1)
                    S = self.Sigma()
                    return x - S.dot(A.T.dot(linalg.solve(A.dot(S.dot(A.T)),c)))
            elif output == 'log_pdf':
                pass
            else:
                raise Exception('Variable "output" should be: '+\
                                '"gmrf","sample",or "log_pdf".')
        elif constraint_type == 'soft':
            pass
        else:
            raise Exception('Input "constraint_type" should be:' + \
                            ' "pointwise", "hard", or "soft"')
    
    
    def iid_gauss(self, n_samples=1):
        """
        Returns a matrix whose columns are N(0,I) vectors of length n 
        """
        return np.random.normal(size=(self.n(),n_samples)) 
        