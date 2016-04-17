from grid.edge import Edge

class Cell(object):
    """
    Description: (Tree of) Rectangular cell(s) in mesh
    
    
    Attributes: 
    
        type - Cells can be one of the following types:
            
            ROOT   - cell on coarsest level
            BRANCH - cell has parent(s) as well as children
            LEAF   - cell on finest refinement level
         
        parent: cell/mesh of which current cell is a sub-cell
         
        children: list of sub-cells of current cell
        
        flag: boolean, used to mark cells
         
        neighbors: addresses of neighboring cells
         
        depth: int, current refinement level 0,1,2,...
         
        rectangle: (x0, x1, y0, y1), where cell = [x0, x1]x[y0, y1]
         
        min_size: double, minimum possible mesh width
     
    
    Methods: 
     
        refine, coarsen, has_children,  
    """
    
    # TODO: --plot_grid
    # TODO: --refine
    # TODO: --coarsen
    # TODO: --balance tree 
    # TODO: Global node and edge_lists?  
    
    # Globals
    NODE_NUM = 0
    VERTEX_LIST = [] 
    EDGE_LIST = []
    
    def __init__(self, parent, vertices, position=None):
        """
        Description: Initializes the cell (sub-)tree
        
        Inputs: 
                    
            parent: parental cell/mesh
            
            vertices: dictionary of coordinates {'SW': (x0,y0), 'SE': (x1,y0), 'NE': (x1,y1), 'NW', (x0,y1) }
            
            rectangle: rectangle defining the cell boundary
            
            position: own position in parent cell (NW, SW, NE, SE) or None if N/A

        """       
        self.parent = parent
        self.children = {'NE': None, 'NW': None, 'SE': None, 'SW': None}
        self.flag = False
        self.position = position
        #
        # Classify Node as ROOT or LEAF
        # 
        if parent.type == 'MESH':
            cell_type = 'ROOT'
            cell_depth = 0  
                     
        else:
            cell_type = 'LEAF'
            cell_depth = parent.depth + 1
        self.depth = cell_depth
        self.type = cell_type
        
        #
        # Position vertices within Cell
        #
        v_sw, v_se, v_ne, v_nw = [vertices[k] for k in ['SW', 'SE', 'NE', 'NW']]
        self.vertices = {'SW': v_sw, 'SE': v_se, 'NE': v_ne, 'NW': v_nw, 
                         'N': None, 'S': None, 'E': None, 'W': None, 
                         'M': None}
       
        #
        # Define bounding rectangle
        #
        coordinates = [vertex.coordinates for vertex in vertices]
        x0, y0 = min(coordinates)
        x1, y1 = max(coordinates)
        self.rectangle = (x0, x1, y0, y1)         
                         
        #
        # Define edges
        # 
        e_we = Edge(v_sw, v_se, self)
        e_sn = Edge(v_se, v_ne, self)
        e_ew = Edge(v_ne, v_nw, self)
        e_ns = Edge(v_nw, v_sw, self)
        self.edges = {'S': e_we, 'E': e_sn, 'N': e_ew, 'W': e_ns}

                                 
    def find_neighbor(self, direction):
        """
        Description: Returns the deepest neighboring cell, whose depth is at most that of the given cell, or
                     'None' if there aren't any neighbors.
         
        Inputs: 
         
            direction: char, 'N'(north), 'S'(south), 'E'(east), or 'W'(west)
             
        Output: 
         
            neighboring node
            
        """

        #
        # For the ROOT cell in a MESH, do a brute force search (comparing vertices)
        #
        if self.type == 'ROOT':
            x = self.vertices
            for sibling in self.parent.children:
                xx = sibling.vertices
                if direction == 'N':
                    is_neighbor = ( x['NW'] == xx['SW'] and x['NE'] == xx['SE'] )
                elif direction == 'S':
                    is_neighbor = ( x['SW'] == xx['NW'] and x['SE'] == xx['NE'] )
                elif direction == 'E':
                    is_neighbor = ( x['SE'] == xx['SW'] and x['NE'] == xx['NW'] )
                elif direction == 'W':
                    is_neighbor = ( x['SW'] == xx['SE'] and x['NW'] == xx['NE'] ) 
                else:
                    print "Invalid direction. Use 'N', 'S', 'E', or 'W'."
                    return None
                    
                if is_neighbor:
                    return sibling
                else:
                    return None
        #
        # Non-ROOT cells 
        # 
        else:
            #
            # Check for neighbors interior to parent cell
            # 
            if direction == 'N':
                interior_neighbors_dict = {'SW': 'NW', 'SE': 'NE'}
            elif direction == 'S':
                interior_neighbors_dict = {'NW': 'SW', 'NE': 'SE'}
            elif direction == 'E':
                interior_neighbors_dict = {'SW': 'SE', 'NW': 'NE'}
            elif direction == 'W':
                interior_neighbors_dict = {'SE': 'SW', 'NE': 'NW'}
            else:
                print "Invalid direction. Use 'N', 'S', 'E', or 'W'."
            
            if interior_neighbors_dict.has_key(self.position):
                neighbor_pos = interior_neighbors_dict[self.position]
                return self.parent.children[neighbor_pos]
            #
            # Check for (children of) parental neighbors
            #
            else:
                mu = self.parent.find_neighbor(direction)
                if mu == None or mu.type == 'LEAF':
                    return mu
                else:
                    #
                    # Reverse dictionary to get exterior neighbors
                    # 
                    exterior_neighbors_dict = \
                       {v: k for k, v in interior_neighbors_dict.iteritems()}
                        
                    if exterior_neighbors_dict.has_key(self.position):
                        neighbor_pos = exterior_neighbors_dict[self.position]
                        return mu.children[neighbor_pos]                        


    def find_leaves(self):
        """
        Returns a list of all leaf sub-cells of a given cell
        """
        leaves = []
        if self.type == 'LEAF':
            leaves.append(self)
        elif self.type == 'ROOT':
            for child in self.children:
                leaves.extend(child.find_leaves())
        else:
            for pos in self.children.keys():
                child = self.children[pos]
                leaves.extend(child.find_leaves())
            
        return leaves
   
    
    def find_root(self):
        '''
        Find the ROOT cell for a given cell
        '''
        if self.type == 'ROOT':
            return self
        else:
            return self.parent.find_root()
        
        
    def plot(self):
        '''
        Plot the current cell with all of its sub-cells
        '''
        pass
    
    
    def contains_point(self, point):
        '''
        Determine whether the given cell contains a point
        
        Input: 
        
            point: tuple (x,y)
            
        Output: 
        
            contains_point: boolean, True if cell contains point, False otherwise
              
        '''
        # TODO: What about points on the boundary?
        # TESTME: contains_point
            
        x,y = point
        x_min, y_min = self.vertices['SW'].coordinate
        x_max, y_max = self.vertices['NE'].coordinate 
        
        if x_min <= x <= x_max and y_min <= y <= y_max:
            return True
        else:
            return False
    
    
    def locate_point(self, point):
        '''
        Returns the smallest cell containing a given point or None if current cell doesn't contain the point
        
        Input:
            
            point: tuple (x,y)
            
        Output:
            
            cell: smallest cell that contains (x,y)
                
        '''
        # TESTME: locate_point
        
        if self.contains_point(point):
            if self.type == 'LEAF': 
                return self
            else:
                #
                # If cell has children, find the child containing the point and continue looking from there
                # 
                for pos in self.children.key():
                    child = self.children[pos]
                    if child.contains_point():
                        return child.locate_point(point)                     
        else:
            return None
    
     
    def mark(self):
        '''
        Mark cell for refinement/coarsening
        '''   
        self.flag = True
    
    
    def unmark(self):
        '''
        Unmark cell
        '''
        self.flag = False
        
        
    def refine(self):
        '''
        Subdivide marked cells in cell
        '''
        pass
        
        
    def coarsen(self):
        '''
        Delete all marked sub-cells
        '''
        
    
    