'''
Created on Apr 11, 2016

@author: hans-werner
'''

class Vertex(object):
    '''
    Description:
    
    Attributes:
    
        coordinate: double, tuple (x,y)
        
        node_number: int, index of vertex in mesh
    
    Methods: 
    '''


    def __init__(self, coordinate, node_number=None):
        '''
        Description: Constructor
        
        Inputs: 
        
            coordinate: double, x- and y- coordinates of vertex
            
            node_number: int, index for vertex  
        '''
        self.coordinate = coordinate
        self.node_number = node_number 