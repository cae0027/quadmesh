"""
Variational Multiscale Method for Advection-Diffusion Equation


"""
from mesh import QuadMesh
from fem import QuadFE, Basis, DofHandler
from function import Explicit, Nodal, Constant
from assembler import Assembler, Form, Kernel
from plot import Plot
import matplotlib.pyplot as plt
import numpy as np
from gmrf import Covariance, GaussianField
from diagnostics import Verbose
from scipy.sparse.linalg import spsolve
from solver import LinearSystem
from scipy.sparse import linalg as spla

# Initialize plot
plot = Plot(quickview=False)
comment = Verbose()

#
# Mesh 
# 

# Computational domain
domain = [-2,2,-1,1]

# Boundary regions
infn = lambda x,y: (x==-2) and (-1<=y) and (y<=0)  # inflow boundary
outfn = lambda x,y: (x==2) and (0<=y) and (y<=1)  # outflow boundary

# Define the mesh
mesh = QuadMesh(box=domain, resolution=(20,10))

# Various refinement levels
for i in range(3):
    if i==0:
        mesh.record(0)
    else:
        mesh.cells.refine(new_label=i)
    
    # Mark inflow
    mesh.mark_region('inflow', infn, entity_type='half_edge', 
                     on_boundary=True, subforest_flag=i)
    
    # Mark outflow
    mesh.mark_region('outflow', outfn, entity_type='half_edge', 
                     on_boundary=True, subforest_flag=i)
    
    
#
# Plot meshes 
#  
""" 
fig, ax = plt.subplots(3,1)  
for i in range(3):
    ax[i] = plot.mesh(mesh,axis=ax[i], 
                      regions=[('inflow','edge'),('outflow','edge')],
                      subforest_flag=i)
    ax[i].set_xlabel('x')
    ax[i].set_ylabel('y')
plt.show()
"""

#
# Define DofHandlers and Basis 
#

# Piecewise Constant Element
Q0 = QuadFE(2,'DQ0')  # element
dh0 = DofHandler(mesh,Q0)  # degrees of freedom handler
dh0.distribute_dofs()
v0 = [Basis(dh0, subforest_flag=i) for i in range(2)]

# Piecewise Linear 
Q1 = QuadFE(2,'Q1')  # linear element
dh1 = DofHandler(mesh,Q1)  # linear DOF handler
dh1.distribute_dofs()

v1   = [Basis(dh1,'v',i) for i in range(3)]   
v1_x = [Basis(dh1,'vx',i) for i in range(3)]
v1_y = [Basis(dh1,'vy',i) for i in range(3)]

# 
# Parameters
# 
a1 = Constant(1)  # advection parameters
a2 = Constant(-0.1) 

# Diffusion coefficient
cov = Covariance(dh0,name='matern',parameters={'sgm': 1,'nu': 1, 'l':0.5})
Z = GaussianField(dh0.n_dofs(), K=cov)

"""
# Plot realizations of the diffusion coefficient
fig, ax = plt.subplots(3,1)
for i in range(3):
    qs = Nodal(basis=v02, data=np.exp(Z.sample()))
    ax[i] = plot.contour(qs,axis=ax[i])
plt.show()
"""

# Sample from the diffusion coefficient
q2 = Nodal(basis=v0[2], data=Z.sample())

# TODO: Assembly of shape functions defined over different submeshes. 

for i in range(2):
    problem = [[Form(trial=v0[i],test=v0[i]), Form(kernel=q2, test=v0[i])]]
    assembler = Assembler(problems,mesh=mesh,subforest_flag=2)
    assembler.assemble()
    assembler.solve()
# Compute the average 
problems = [[Form(trial=v00,test=v00), Form(kernel=q2, test=v00)],
            [Form(trial=v01,test=v01), Form(kernel=q2, test=v01)]]

assembler = Assembler(problems, mesh=mesh, subforest_flag=2)
assembler.assemble()

# Get approximation on coarsest level
M0 = assembler.get_matrix(i_problem=0)
b0 = assembler.get_vector(i_problem=0)

solver = LinearSystem(v00,M0,b0)
solver.solve_system()
q0 = solver.get_solution()

# Approximation on intermediate level
M1 = assembler.get_matrix(i_problem=1)
b1 = assembler.get_vector(i_problem=1)
solver = LinearSystem(v01,M1,b1)
solver.solve_system()
q1 = solver.get_solution()


fig, ax = plt.subplots(3,1)
for i,q in enumerate([q0,q1,q2]):
    ax[i] = plot.contour(q,axis=ax[i])
plt.show()

#
# Solve the Linear System on Each Mesh
# 
xi0 = Kernel(q0,F=lambda q: 1 + np.exp(q))
xi1 = Kernel(q1,F=lambda q: 1 + np.exp(q))
xi2 = Kernel(q2,F=lambda q: 1 + np.exp(q)) 

"""
Form(kernel=a1, test=v12, trial=v12_x),
         Form(kernel=a2, test=v12, trial=v12_y),
"""
prob0 = [Form(kernel=xi2,test=v12_x, trial=v12_x), 
         Form(kernel=xi2,test=v12_y,trial=v12_y),
         Form(kernel=a1, test=v12, trial=v12_x),
         Form(kernel=a2, test=v12, trial=v12_y),
         Form(kernel=0, test=v12)]

assembler = Assembler(prob0, mesh=mesh, subforest_flag=2)
assembler.add_dirichlet('inflow', 1)
assembler.add_dirichlet('outflow',0)
print(assembler.get_dirichlet())
#assembler.add_dirichlet(None)
assembler.assemble()
K = np.array(assembler.get_matrix())
#print(K)
u0 = assembler.solve()
u0 = Nodal(basis=v12, data=u0)

fig, ax = plt.subplots(1,1)
ax = plot.contour(u0,axis=ax)
plt.show()

"""
K = assembler.get_matrix().tocsr()
b = assembler.get_vector()
x0 = assembler.assembled_bnd()
u0 = np.zeros((v10.n_dofs(),1))
int_dofs = assembler.get_dofs('interior')

u0[int_dofs,0] = spsolve(K,b-x0)

# Resolve Dirichlet conditions
dir_dofs, dir_vals = assembler.get_dirichlet(asdict=False)
u0[dir_dofs] = dir_vals



solver = LinearSystem(v10,K,b)
solver.solve_system()

u0 = solver.get_solution()
"""
#