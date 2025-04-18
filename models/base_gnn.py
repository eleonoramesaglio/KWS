import tensorflow as tf
import tensorflow_gnn as tfgnn
import numpy as np 
from tensorflow_gnn.models.gcn import gcn_conv
from tensorflow_gnn.models.gat_v2.layers import GATv2Conv
#tf.config.run_functions_eagerly(True) 
#tf.data.experimental.enable_debug_mode()



def mfccs_to_graph_tensors_for_dataset_OLD(mfcc, adjacency_matrices, label):

    # Print shapes to debug
  #  tf.print("MFCC shape:", tf.shape(mfcc))
  #  tf.print("Adjacency shape:", tf.shape(adjacency_matrix))
  #  tf.print("Label shape:", tf.shape(label))


    adjacency_matrix = adjacency_matrices[0]

   
    adjacency_matrices = adjacency_matrices[1:]


    # Ensure current shape of MFCC (98 frames, 39 MFCCs)
    mfcc_static = tf.reshape(mfcc, [98, 39]) 

    
    # Get edges from adjacency matrix
    edges = tf.where(adjacency_matrix > 0)  # Returns indices where adjacency > 0

    # Get corresponding weights of edges from adjacency matrix
    # e.g. edges has saved [0,3] --> goes into adjacency[0,3] and gets the weight
    weights = tf.gather_nd(adjacency_matrix, edges)  
    
    # The edges tensor has shape [num_edges, 2] where each row is [source, target]
    sources = edges[:, 0]
    targets = edges[:, 1]


    # Create GraphTensor
    graph_tensor = tfgnn.GraphTensor.from_pieces(
        node_sets={
            "frames": tfgnn.NodeSet.from_fields(
                    
                
                features={"features": mfcc_static},  
                sizes=[tf.shape(mfcc_static)[0]]
            )
        },
        edge_sets={
            "connections": tfgnn.EdgeSet.from_fields(
                features={"weights" : weights},
                sizes=[tf.shape(edges)[0]],
                adjacency=tfgnn.Adjacency.from_indices(
                    source=("frames", sources),
                    target=("frames", targets)
                )
            )
        }
    )
        

    
    return graph_tensor, label



def mfccs_to_graph_tensors_for_dataset(mfcc, adjacency_matrices, label):
    """
    Convert MFCC features and adjacency matrices to a graph tensor where
    each adjacency matrix becomes a separate edge set in the graph.
    
    Args:
        mfcc: MFCC features
        adjacency_matrices: List of adjacency matrices, each will become an edge set
        label: Class label
    
    Returns:
        A tuple (graph_tensor, label) where graph_tensor contains multiple edge sets
    """
    # Ensure current shape of MFCC (98 frames, 39 MFCCs)
    mfcc_static = tf.reshape(mfcc, [98, 39])
    
    # Create the node set that will be shared by all edge sets
    node_sets = {
        "frames": tfgnn.NodeSet.from_fields(
            features={"features": mfcc_static},  
            sizes=[tf.shape(mfcc_static)[0]]
        )
    }
    
    # Create an edge set for each adjacency matrix
    edge_sets = {}
    
    # Unstack the matrices so we can iterate over them
    unstacked_matrices = tf.unstack(adjacency_matrices, axis=0)

    for i, adjacency_matrix in enumerate(unstacked_matrices):
        # Get edges from this adjacency matrix
        edges = tf.where(adjacency_matrix > 0)
        
        # Get corresponding weights
        weights = tf.gather_nd(adjacency_matrix, edges)

      #  weights = tf.reshape(weights, [-1, 1])
        
        # Extract source and target indices
        sources = edges[:, 0]
        targets = edges[:, 1]
        
        # Create edge set with unique names
        edge_set_name = f"connections_{i}"
        
        edge_sets[edge_set_name] = tfgnn.EdgeSet.from_fields(
            features={"weights" : weights}, 
            sizes=[tf.shape(edges)[0]],
            adjacency=tfgnn.Adjacency.from_indices(
                source=("frames", sources),
                target=("frames", targets)
            )
        )
    
    # Create the graph tensor with all node sets and edge sets
    graph_tensor = tfgnn.GraphTensor.from_pieces(
        node_sets=node_sets,
        edge_sets=edge_sets
    )
    
    return graph_tensor, label


def mfccs_to_graph_tensors(mfccs, adjacency_matrices):
    """
    Convert MFCC features to graph tensors using custom adjacency matrices.
    
    Args:
        mfccs: Tensor of shape [batch_size, n_frames, n_features]
        adjacency_matrices: Tensor of shape [batch_size, n_frames, n_frames]
        
    Returns:
        List of GraphTensor objects
    """

    # Extract single example
    features = mfccs  # Shape: [n_frames, n_features]
    adjacency = adjacency_matrices  # Shape: [n_frames, n_frames]
    
    # Get edges from adjacency matrix
    edges = tf.where(adjacency > 0)  # Returns indices where adjacency > 0

    # Get corresponding weights of edges from adjacency matrix
    # e.g. edges has saved [0,3] --> goes into adjacency[0,3] and gets the weight
    weights = tf.gather_nd(adjacency, edges)  #### possibly don't use that ????
    
    # The edges tensor has shape [num_edges, 2] where each row is [source, target]
    sources = edges[:, 0]
    targets = edges[:, 1]
    
    # Create GraphTensor
    graph_tensor = tfgnn.GraphTensor.from_pieces(
        node_sets={
            "frames": tfgnn.NodeSet.from_fields(
                
                
                features={"features": features},
                sizes=[tf.shape(features)[0]]
            )
        },
        edge_sets={
            "connections": tfgnn.EdgeSet.from_fields(
                features={"weights" : weights}, # possibly here just adjacency ?????
                # but I think okay like this, since the adjacency below defines which edges
                # exist and then by normal indexing, it takes the correct weights
                # per edge
                sizes=[tf.shape(edges)[0]],
                adjacency=tfgnn.Adjacency.from_indices(
                    source=("frames", sources),
                    target=("frames", targets)
                )
            )
        }
    )
    

    
    return graph_tensor




def base_gnn_model(
        graph_tensor_specification,
        initial_nodes_mfccs_layer_dims = 64,
        initial_edges_weights_layer_dims = [16],
        message_dim = 128,
        next_state_dim = 128,
        num_classes = 35,
        l2_reg_factor = 6e-6,
        dropout_rate = 0.2,
        use_layer_normalization = True,
        n_message_passing_layers = 4,
        dilation = False,
        n_dilation_layers = 2,


        ):
    
    """


    Note that the dilation happens circular wise, i.e. if we have 4 message passing layers and 2 dilation layers, 
    we have in the first layer connections_0 (i.e. the undilated matrix), then in 2nd connections_1 (dilated by factor 2 currently,
    but generally can be chosen by user how to to dilation), then connections_0 again, and then connections_1 again.

    Base GNN Model :

    - We have n_frames many nodes and each pack the MFCCs as features 
    - The adjacency matrix is solely 0 and 1

    graph_tensor_specification : the "description" of the input graph 
    initial_nodes_mfccs_layer_dims, initial_edges_weights_layer_dims : the initial dimensions for encoding of features
    message_dim, next_state_dim : dimensions for the message passing algorithm

    """


    

    # Input is the graph structure 
    input_graph = tf.keras.layers.Input(type_spec = graph_tensor_specification)

    # Convert to scalar GraphTensor
    # TODO : is this even needed ? what does it do ?
    graph = tfgnn.keras.layers.MapFeatures()(input_graph)

    is_batched = (graph.spec.rank == 1)


    """
    edge_sets = graph.edge_sets 


    for edge_set_name, edge_set in edge_sets.items():
        source_indicies = edge_set.adjacency.source
        target_indices = edge_set.adjacency.target
  
        edge_features = {}

        for feature_name, feature_value in edge_set.features.items():
            edge_features[feature_name] = feature_value 

        print('h')
    """




    ### IMPORTANT: All TF-GNN modeling code assumes a GraphTensor of shape []
    ### in which the graphs of the input batch have been merged to components of
    ### one contiguously indexed graph. There are no edges between components,
    ### so no information flows between them.
    if is_batched:
        batch_size = graph.shape[0]
        #merge all graphs of the batch into one, contiguously indexed graph.
        #  The resulting GraphTensor has shape [] (i.e., is scalar) and its features h
        # ave the shape [total_num_items, *feature_shape] where total_num_items is the sum 
        # of the previous num_items per batch element. At that stage, the GraphTensor is ready
        #  for use with the TF-GNN model-building code, but it is no longer easy to split it up.
        # https://github.com/tensorflow/gnn/blob/main/tensorflow_gnn/docs/guide/graph_tensor.md
        # this means our nodes [32,98,39] are now [32*98,39] = [3136,39]
        graph = graph.merge_batch_to_components()





    # TODO : understand : the initial node state is also learnt during training ? should be, but then is 64 dims ever used
    # or basically one the message_passing_dim all the time ? 
    # Define the initial hidden states for the nodes
    def set_initial_node_state(node_set,node_set_name):
        """
        Initialize hidden states for nodes in the graph.
        
        Args:
            node_set: A dictionary containing node features
            node_set_name: The name of the node set (e.g., "frames")
            
        Returns:
            A transformation function applied to the node features
        """
        if node_set_name == "frames":
            # Apply a dense layer to transform MFCC features into hidden states
            # Instead of just one dense layer , we can also directly use dropout etc. here (if we wish so) 
            return tf.keras.layers.Dense(initial_nodes_mfccs_layer_dims, activation="relu")(
                node_set["features"]  # This would be your mfcc_static features
            )
        else:
            # Handle any other node types
            raise ValueError(f"Unknown node set: {node_set_name}")
            
    def set_initial_edge_state(edge_set, edge_set_name):
        """
        Initialize hidden states for edges in the graph
        
        
        """
        # TODO : can be implemented if we want 
        pass 


    def set_initial_context_state():
        """
        Initialize hidden state for the context of the graph (i.e. the whole graph)
        
        """
        # TODO : can be implemented if we want
        pass
        

    graph = tfgnn.keras.layers.MapFeatures(
        node_sets_fn = set_initial_node_state, name = 'init_states')(graph)
    
    # Let us now build some basic building blocks for our model
    def dense(units, use_layer_normalization = False):
        """ Dense layer with regularization (L2 & Dropout) & normalization"""
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        result = tf.keras.Sequential([
            tf.keras.layers.Dense(
                units,
                activation = "relu",
                use_bias = True,
                kernel_regularizer = regularizer,
                bias_regularizer = regularizer),
            tf.keras.layers.Dropout(dropout_rate)])
        if use_layer_normalization:
            result.add(tf.keras.layers.LayerNormalization())
        return result 
    

    # Without edge weights
    # If we have a unweighted adjacency matrix (window case), the function convolution_with_weights will return the same result as the normal convolution
    # If instead we have a weighted adjacency matrix, convolution_with_weights implements a sort of "attention mechanism", giving more importance
    # to the edges with higher weights.

    #This layer can compute a convolution over an edge set by applying the
    #  passed-in message_fn (dense(message_dim) here) for all edges on the 
    # concatenated inputs from some or all of: the edge itself, the sender node, and the receiver node, followed by pooling to the receiver node.


    # message_fn : layer that computes the individual messages after they went through the "combine_type" aggregation (i.e. here rn from our target & source node the embeddings?)
    # combine_type : defines how to combine the messages before passing them through the message layer (i.e concat, sum (element-wise) etc.)
    # --> this combines right now the node features (of target & source node of the corresponding edge //
    # NO : just the target or source node, depending opn what the receiver tag is (so doesn't use the information of the node
    # that it is sending to)) and also edge features etc. if they are any (just combines all of them)
    # reduce_type : Specifices how to combine the messages (of ALL the nodes) after passing them through the message layer (max/min/mean...)
    # receiver_tag : defines the receiver of those messages (i.e. here in our implementation which node receives them)
    # receiver_tag  : could also be context node here and then we pool information into the context node!!! read the documentation on simpleconv!

    # TODO : we can design our own convolution function !
    def convolution(message_dim, receiver_tag):



        return tfgnn.keras.layers.SimpleConv(dense(message_dim), "sum", receiver_tag = receiver_tag)
    
    # Function: AGGREGATION
    # The convolution function is used to AGGREGATE messages from the neighbors of a node to update its state.
    # There are two functions deciding the type of aggregation: reduce_type and combine_type.
    # The reduce_type specifies how to combine the messages from the neighbors (e.g., sum, mean, max).
    # The combine_type is instead used when there are multiple messages (deriving from multiple features) from the same neighbor.
    # It decides how to aggregate these messages (usually they are concatenated) before passing them to the receiver node.
    # The receiver_tag specifies the node that will receive the aggregated messages.

    def next_state(next_state_dim, use_layer_normalization):
        return tfgnn.keras.layers.NextStateFromConcat(dense(next_state_dim, use_layer_normalization=use_layer_normalization))
    


    # Function: COMPUTE NEXT STATE
    # The next_state function is used to update the state of a node after aggregating messages from its neighbors.
    # 1. Concatenates the node's current state with the aggregated messages
    # 2. Processes them through a dense layer with regularization & normalization to produce the new state.
    # 3. Returns the new state for the node, with dimensions specified by next_state_dim.
    # This function is then used in the NodeSetUpdate layer to update the node states.

   
    

    # The GNN "core" of the model 
    # Convolutions let data flow towards the specified endpoint of edges
    # Note that the order here defines how the updates happen (so first e.g. NodeSetUpdate, then 
    # EdgeSetUpdate etc. (? is that true or in parallel ?))
    # NodeSetUpdate : receives the input graph and returns a new hidden state for the node set it gets applied
    # to. The new hidden state is computed with the given next-state layer from the node set's prior state and the
    # aggregated results from each incoming edge set

    # For example, each round of this model computes a new state for the node set "frames" by applying 
    # dense(next_state_dim) (i.e. the next_state function) to the concatenation of (since we do 
    # NextStateFromConcat) the result of convolution(message_dim)(graph, edge_set_name= "connections")
    # (i.e. here we dont even need to concat because we just have one set of edges I believe)

    # A convolution on an edge set computes a value for each edge (a "message") as a trainable function of the node states
    # at both endpoints (of the edge) and then aggregates the results at the receiver nodes by forming the sum
    # (or mean or max) (i.e. that is the aggregation method in convolution) over all incoming edges

    # For example, the convolution on edge set "connections" concatenates the node state of each edge's incident
    # "node1" & "node2" (??) node, applies dense(message_dim) (so I guess since we use dense layer of size 64
    # for the nodes, when we concatenate two we have 64+64 = 128 and therefore message_dim needs to be 128 ?)
    # and sums (or avgs, max,...) the results over the edges incident to each SOURCE node (this means at the SOURCE
    # node, all incoming messages are summed (or avgs,max,...) together!)
    # I think for us we could do source or target, since we have anyway undirected edges (i.e. if node a & b
    # are connected, they will both appear once as source and once as target)
    

    ### From : https://colab.research.google.com/github/tensorflow/gnn/blob/master/examples/notebooks/ogbn_mag_indepth.ipynb#scrollTo=jd02cyRB5DP1
    #Notice that the conventional names *source* and *target* for the endpoints of a directed edge
    #  do **not** prescribe the direction of information flow: each "written" edge logically goes from a 
    # paper to its author (so the "author" node is its `TARGET`), yet this model lets the data flow towards 
    # the paper (and the "paper" node is its `SOURCE`). In fact, sampled subgraphs have edges directed away
    #  from the root node, so data flow towards the root often goes from `TARGET` to `SOURCE`.



    #The code below creates fresh Convolution and NextState layer objects for each edge set and node set, 
    # resp., and for each round of updates. This means they all have separate trainable weights. If
    #  desired, weight sharing is possible in the standard Keras way by sharing convolution and 
    # next-state layer objects, provided the input sizes match.

    #For more information on defining your own GNN models (including those with edge and context states), 
    # please refer to the [TF-GNN Modeling Guide](https://github.com/tensorflow/gnn/blob/main/tensorflow_gnn/docs/guide/gnn_modeling.md).


    # n_message_passing_layers defines from how far in neighbour terms we are getting information (i.e. when 4, this means any node in the graph
    # accumulates information from 4 neighbours away (. -- . -- . -- . -- .) : Node 1 has some info of Node 5 embedded in itself.)

    # Note that initially, the nodes are (3136,39) and after the first message passing layer, they are (3136,128) !

    if not dilation:
        # Like this, in the modulo calculation, we only use connections_0 all the time, i.e. we do not use dilation
        n_dilation_layers = 1


    for i in range(n_message_passing_layers):
        dil_layer_num = i % n_dilation_layers # circular usage of dilated adjacency matrices throughout message passing layers
        graph = tfgnn.keras.layers.GraphUpdate(
            node_sets = {
                "frames" : tfgnn.keras.layers.NodeSetUpdate(
                    {f"connections_{dil_layer_num}" : convolution(message_dim, tfgnn.SOURCE)},
                next_state(next_state_dim, use_layer_normalization)
                )
            }
        )(graph)







    # Take all the 98 learnt node features , aggregate them using sum
    # which is then representing the context vector (i.e. the "graph node")
    pooled_features = tfgnn.keras.layers.Pool(
        tfgnn.CONTEXT, "sum", node_set_name = "frames")(graph)  
    logits = tf.keras.layers.Dense(num_classes)(pooled_features)


    
    model = tf.keras.Model(input_graph, logits)


    return model 



def base_gnn_model_learning_edge_weights(
        graph_tensor_specification,
        initial_nodes_mfccs_layer_dims = 64,
        initial_edges_weights_layer_dims = 64,
        message_dim = 128,
        next_state_dim = 128,
        num_classes = 35,
        l2_reg_factor = 6e-6,
        dropout_rate = 0.2,
        use_layer_normalization = True,
        n_message_passing_layers = 4,
        dilation = False,
        n_dilation_layers = 2,


        ):
    
    """

    A base GNN model, NOT utilizing the pre-calculated weights of the adjacency matrix,
    but learning the weights during training.

    """

    

    # Input is the graph structure 
    input_graph = tf.keras.layers.Input(type_spec = graph_tensor_specification)

    # Convert to scalar GraphTensor
    graph = tfgnn.keras.layers.MapFeatures()(input_graph)

    is_batched = (graph.spec.rank == 1)



    if is_batched:
        batch_size = graph.shape[0]
        graph = graph.merge_batch_to_components()


    def map_edge_features(edge_set, edge_set_name):
        if edge_set_name == "connections_0":
            return {"weights": tf.expand_dims(edge_set["weights"], axis=-1)}
        return edge_set.features

    graph = tfgnn.keras.layers.MapFeatures(
        edge_sets_fn=map_edge_features
    )(graph)


    def set_initial_node_state(node_set,node_set_name):
        """
        Initialize hidden states for nodes in the graph.
        
        Args:
            node_set: A dictionary containing node features
            node_set_name: The name of the node set (e.g., "frames")
            
        Returns:
            A transformation function applied to the node features
        """
        if node_set_name == "frames":
            # Apply a dense layer to transform MFCC features into hidden states
            # Instead of just one dense layer , we can also directly use dropout etc. here (if we wish so) 
            return tf.keras.layers.Dense(initial_nodes_mfccs_layer_dims, activation="relu")(
                node_set["features"]  
            )
        else:
            # Handle any other node types
            raise ValueError(f"Unknown node set: {node_set_name}")
            
    def set_initial_edge_state(edge_set, edge_set_name):
        """
        Initialize hidden states for edges in the graph.
        Right now we just learn for the non-dilated adjacency matrix (i.e. connections_0)
        """
        if edge_set_name == "connections_0":

            return tf.keras.layers.Dense(initial_edges_weights_layer_dims, activation="relu")(edge_set['weights'])

        else:
            # Handle any other edge types
            raise ValueError(f"Unknown node set: {edge_set_name}")


    def set_initial_context_state():
        """
        Initialize hidden state for the context of the graph (i.e. the whole graph)
        
        """
        # TODO : can be implemented if we want
        pass
        

    graph = tfgnn.keras.layers.MapFeatures(
        node_sets_fn = set_initial_node_state,
        edge_sets_fn = set_initial_edge_state,
          name = 'init_states')(graph)
    
    # Let us now build some basic building blocks for our model
    def dense(units, use_layer_normalization = False):
        """ Dense layer with regularization (L2 & Dropout) & normalization"""
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        result = tf.keras.Sequential([
            tf.keras.layers.Dense(
                units,
                activation = "relu",
                use_bias = True,
                kernel_regularizer = regularizer,
                bias_regularizer = regularizer),
            tf.keras.layers.Dropout(dropout_rate)])
        if use_layer_normalization:
            result.add(tf.keras.layers.LayerNormalization())
        return result 
    


    def convolution(message_dim, receiver_tag):
        return tfgnn.keras.layers.SimpleConv(dense(message_dim), "sum", receiver_tag = receiver_tag,
                                             sender_edge_feature= tfgnn.HIDDEN_STATE) # SENDER EDGE FEATURE NEEDED HERE, WHEN WE USE SET INITIAL EDGE STATE!!!
    

    def next_state(next_state_dim, use_layer_normalization):
        return tfgnn.keras.layers.NextStateFromConcat(dense(next_state_dim, use_layer_normalization=use_layer_normalization))
    



    if not dilation:
        # Like this, in the modulo calculation, we only use connections_0 all the time, i.e. we do not use dilation
        n_dilation_layers = 1


    for i in range(n_message_passing_layers):
        dil_layer_num = i % n_dilation_layers # circular usage of dilated adjacency matrices throughout message passing layers
        # https://github.com/tensorflow/gnn/blob/main/tensorflow_gnn/docs/api_docs/python/tfgnn/keras/layers/NodeSetUpdate.md
        graph = tfgnn.keras.layers.GraphUpdate(

            #https://github.com/tensorflow/gnn/blob/main/tensorflow_gnn/docs/api_docs/python/tfgnn/keras/layers/EdgeSetUpdate.md
            #selects input features from the edge and its incident nodes, then passes them through a next-state layer
            edge_sets = {
                "connections_0" : tfgnn.keras.layers.EdgeSetUpdate(
                    next_state = next_state(next_state_dim, use_layer_normalization),
                    edge_input_feature = tfgnn.HIDDEN_STATE
                  
                )
            },

            node_sets = {
                "frames" : tfgnn.keras.layers.NodeSetUpdate(
                    {f"connections_{dil_layer_num}" : convolution(message_dim, tfgnn.SOURCE)},
                next_state(next_state_dim, use_layer_normalization)
                )
            },
        )(graph)




    # Take all the 98 learnt node features , aggregate them using sum
    # which is then representing the context vector (i.e. the "graph node")
    pooled_features = tfgnn.keras.layers.Pool(
        tfgnn.CONTEXT, "sum", node_set_name = "frames")(graph)  
    logits = tf.keras.layers.Dense(num_classes)(pooled_features)


    
    model = tf.keras.Model(input_graph, logits)


    return model 



def GAT_GCN_model(
        
        graph_tensor_specification,
        initial_nodes_mfccs_layer_dims = 64,
        initial_edges_weights_layer_dims = [16],
        message_dim = 128,
        next_state_dim = 128,
        num_classes = 35,
        l2_reg_factor = 6e-6,
        dropout_rate = 0.2,
        use_layer_normalization = True,
        n_message_passing_layers = 4,
        dilation = False,
        n_dilation_layers = 2,


        ):
    

    """ GAT for context node, GCN for node features """


    # Input is the graph structure 
    input_graph = tf.keras.layers.Input(type_spec = graph_tensor_specification)

    # Convert to scalar GraphTensor
    # TODO : is this even needed ? what does it do ?
    graph = tfgnn.keras.layers.MapFeatures()(input_graph)

    is_batched = (graph.spec.rank == 1)



    if is_batched:
        batch_size = graph.shape[0]
        graph = graph.merge_batch_to_components()





    # Define the initial hidden states for the nodes
    def set_initial_node_state(node_set,node_set_name):
        """
        Initialize hidden states for nodes in the graph.
        
        Args:
            node_set: A dictionary containing node features
            node_set_name: The name of the node set (e.g., "frames")
            
        Returns:
            A transformation function applied to the node features
        """


        def dense_inner(units, use_layer_normalization = False, normalization_type = "normal"):
            regularizer = tf.keras.regularizers.l2(l2_reg_factor)
            result = tf.keras.Sequential([
                tf.keras.layers.Dense(
                    units,
                    activation = "relu",
                    use_bias = True,
                    kernel_regularizer = regularizer,
                    bias_regularizer = regularizer),
                tf.keras.layers.Dropout(dropout_rate)])
            if use_layer_normalization:
                if normalization_type == 'normal':
                    result.add(tf.keras.layers.LayerNormalization())
                elif normalization_type == 'group':
                    result.add(tf.keras.layers.GroupNormalization(message_dim))
            return result 


        if node_set_name == "frames":


            features = node_set["features"]

            # Split the diff. features such that we can do separate layer learning


            # TODO : try to do base mfcc + its energy, delta + energy, delta-delta + energy
            base_mfccs = features[: , 0:12]
            delta_mfccs = features[: , 12:24]
            delta_delta_mfccs = features[:, 24:36]
            energy_features = features[:, 36:39]

            base_processed = dense_inner(24, use_layer_normalization=True)(base_mfccs)
            delta_processed = dense_inner(24, use_layer_normalization=True)(delta_mfccs)
            delta_delta_processed = dense_inner(24, use_layer_normalization=True)(delta_delta_mfccs)
            energy_processed = dense_inner(8, use_layer_normalization=True)(energy_features)

            # Concatenate the processed features
            combined_features = tf.keras.layers.Concatenate()(
                [base_processed, delta_processed, delta_delta_processed, energy_processed]
            )
            


            return dense_inner(initial_nodes_mfccs_layer_dims, use_layer_normalization=True)(combined_features)
            
        else:
            # Handle any other node types
            raise ValueError(f"Unknown node set: {node_set_name}")
            
    def set_initial_edge_state(edge_set, edge_set_name):
        """
        Initialize hidden states for edges in the graph
        
        
        """
        # TODO : can be implemented if we want 
        pass 


    def set_initial_context_state(context):
        """
        Initialize hidden state for the context of the graph (i.e. the whole graph)
        
        """

        # Option 1 : initialize the context node with a zero vector
        return tfgnn.keras.layers.MakeEmptyFeature()(context)
        

    graph = tfgnn.keras.layers.MapFeatures(
        node_sets_fn = set_initial_node_state,
        context_fn= set_initial_context_state, name = 'init_states')(graph)
    
    # Let us now build some basic building blocks for our model
    def dense(units, use_layer_normalization = False):
        """ Dense layer with regularization (L2 & Dropout) & normalization"""
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        result = tf.keras.Sequential([
            tf.keras.layers.Dense(
                units,
                activation = "relu",
                use_bias = True,
                kernel_regularizer = regularizer,
                bias_regularizer = regularizer),
            tf.keras.layers.Dropout(dropout_rate)])
        if use_layer_normalization:
            result.add(tf.keras.layers.LayerNormalization())
        return result 
    

    def gat_convolution(num_heads, receiver_tag):
        # Here we now use a GAT layer

        regularizer = tf.keras.regularizers.l2(l2_reg_factor)


        return  GATv2Conv(
            num_heads = num_heads,
            per_head_channels = 32, # dimension of vector of output of each head
            heads_merge_type = 'concat', # how to merge the heads
            receiver_tag = receiver_tag, # also possible nodes/edges ; see documentation of function !
            receiver_feature = tfgnn.HIDDEN_STATE,
            sender_node_feature = tfgnn.HIDDEN_STATE,
            sender_edge_feature= None,
            kernel_regularizer= regularizer,

        )
    

    def gcn_convolution(message_dim, receiver_tag):
        # Here we now use a GCN layer 
        # TODO : don't understand how to add dropout ; I think
        # we would need to add it into the GCNConv class itself, since
        # we are not calling a keras layer here, but the whole class 
        # (i.e. we cannot use the sequential function like normally)
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)


        return  gcn_conv.GCNConv(
            units = message_dim,
            receiver_tag= receiver_tag,
            activation = "relu",
            use_bias = True,
            kernel_regularizer = regularizer,
            add_self_loops = False,
            edge_weight_feature_name= 'weights',
            degree_normalization= 'in'
        )


    def next_state(next_state_dim, use_layer_normalization):
        return tfgnn.keras.layers.NextStateFromConcat(dense(next_state_dim, use_layer_normalization=use_layer_normalization))
    



    if not dilation:
        # Like this, in the modulo calculation, we only use connections_0 all the time, i.e. we do not use dilation
        n_dilation_layers = 1 


    
    for i in range(n_message_passing_layers):
        dil_layer_num = i % n_dilation_layers # circular usage of dilated adjacency matrices throughout message passing layers
        graph = tfgnn.keras.layers.GraphUpdate(
            node_sets = {
                "frames" : tfgnn.keras.layers.NodeSetUpdate(
                    {f"connections_{dil_layer_num}" : gcn_convolution(message_dim, tfgnn.TARGET)},
                next_state(next_state_dim, use_layer_normalization)
                )
            },

            context = tfgnn.keras.layers.ContextUpdate(
                {
                    "frames" : gat_convolution(num_heads= 3, receiver_tag = tfgnn.CONTEXT)
                },
                next_state(next_state_dim, use_layer_normalization)
            
        ))(graph)



    # Get the current context state (has shape (batch_size, 128) , where 128 is the message_passing_dimension)
    # This represents the master node, which is updated in each message passing layer !
    context_state = graph.context.features['hidden_state']

    # Dropout # TODO: like in speechreco paper, see if it works/ m
    context_state = tf.keras.layers.Dropout(dropout_rate)(context_state)

    logits = tf.keras.layers.Dense(num_classes)(context_state)

    model = tf.keras.Model(input_graph, logits)

    return model 


def base_GATv2_model(
        graph_tensor_specification,
        initial_nodes_mfccs_layer_dims = 64,
        initial_edges_weights_layer_dims = [16],
        message_dim = 128,
        next_state_dim = 128,
        num_classes = 35,
        l2_reg_factor = 6e-6,
        dropout_rate = 0.2,
        use_layer_normalization = True,
        n_message_passing_layers = 4,
        dilation = False,
        n_dilation_layers = 2,




        ):
    
    """
        using GATv2. 

        https://github.com/tensorflow/gnn/blob/main/tensorflow_gnn/models/gat_v2/layers.py

        Notice how this implements its own attention mechanism on edge weights. This means,
        in each message passing layer, the node receives messages from multiple different
        nodes , but unlike in our current implementation, these weights are not static (
        so not just adjacency 1 or 0 or weighted temporally & in similarity) but are learnt.
        Therefore, we use here our normal, unweighted adjacency matrix ! (set in main
        mode to "window" TODO : think similarity works aswell, such that edge connections are
        already initialized in a nicer way ; I think since we don't use the weights of the edges,
        it doesn't matter, but to be sure, lets initialize with our idea, but set wherever there
        is an edge to 1 and else 0)


        In this basic implementation, we use the attention mechanism to gather information from our
        nodes hidden states into the context 
        node, i.e. we initialize in the beginning a context node.
        Here, much more is possible ; look into the documentation !

        using also weighted adjacency matrix for in-between nodes


    """


    

    # Input is the graph structure 
    input_graph = tf.keras.layers.Input(type_spec = graph_tensor_specification)

    # Convert to scalar GraphTensor
    # TODO : is this even needed ? what does it do ?
    graph = tfgnn.keras.layers.MapFeatures()(input_graph)

    is_batched = (graph.spec.rank == 1)



    if is_batched:
        batch_size = graph.shape[0]
        graph = graph.merge_batch_to_components()





    # TODO : understand : the initial node state is also learnt during training ? should be, but then is 64 dims ever used
    # or basically one the message_passing_dim all the time ? 
    # Define the initial hidden states for the nodes
    def set_initial_node_state(node_set,node_set_name):
        """
        Initialize hidden states for nodes in the graph.
        
        Args:
            node_set: A dictionary containing node features
            node_set_name: The name of the node set (e.g., "frames")
            
        Returns:
            A transformation function applied to the node features
        """
        if node_set_name == "frames":
            # Apply a dense layer to transform MFCC features into hidden states
            # Instead of just one dense layer , we can also directly use dropout etc. here (if we wish so) 
            return tf.keras.layers.Dense(initial_nodes_mfccs_layer_dims, activation="relu")(
                node_set["features"] 
            )
        else:
            # Handle any other node types
            raise ValueError(f"Unknown node set: {node_set_name}")
            
    def set_initial_edge_state(edge_set, edge_set_name):
        """
        Initialize hidden states for edges in the graph
        
        
        """
        # TODO : can be implemented if we want 
        pass 


    def set_initial_context_state(context):
        """
        Initialize hidden state for the context of the graph (i.e. the whole graph)
        
        """

        # Option 1 : initialize the context node with a zero vector
        return tfgnn.keras.layers.MakeEmptyFeature()(context)
        

    graph = tfgnn.keras.layers.MapFeatures(
        node_sets_fn = set_initial_node_state,
        context_fn= set_initial_context_state, name = 'init_states')(graph)
    
    # Let us now build some basic building blocks for our model
    def dense(units, use_layer_normalization = False):
        """ Dense layer with regularization (L2 & Dropout) & normalization"""
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        result = tf.keras.Sequential([
            tf.keras.layers.Dense(
                units,
                activation = "relu",
                use_bias = True,
                kernel_regularizer = regularizer,
                bias_regularizer = regularizer),
            tf.keras.layers.Dropout(dropout_rate)])
        if use_layer_normalization:
            result.add(tf.keras.layers.LayerNormalization())
        return result 
    

    def gat_convolution(num_heads, receiver_tag):
        # Here we now use a GAT layer

        regularizer = tf.keras.regularizers.l2(l2_reg_factor)


        return  GATv2Conv(
            num_heads = num_heads,
            per_head_channels = 128, # dimension of vector of output of each head
            heads_merge_type = 'concat', # how to merge the heads
            receiver_tag = receiver_tag, # also possible nodes/edges ; see documentation of function !
            receiver_feature = tfgnn.HIDDEN_STATE,
            sender_node_feature = tfgnn.HIDDEN_STATE,
            sender_edge_feature= None,
            kernel_regularizer= regularizer,


        )
    

    class WeightedSumConvolution(tf.keras.layers.Layer):

        def __init__(self, message_dim, receiver_tag):
            super().__init__()
            self.message_dim = message_dim
            self.receiver_tag = receiver_tag
            self.sender_tag = tfgnn.SOURCE if receiver_tag == tfgnn.TARGET else tfgnn.TARGET
            self.dense = dense(units = message_dim, use_layer_normalization = use_layer_normalization)
        
        def call(self, graph, edge_set_name):
            # Get node states
            messages = tfgnn.broadcast_node_to_edges(
                graph,
                edge_set_name,
                self.sender_tag,
                feature_name="hidden_state") # Take the hidden state of the node
            
            # Get edge weights
            weights = graph.edge_sets[edge_set_name].features['weights']
            
            # Apply weights to messages
            weighted_messages = tf.expand_dims(weights, -1) * messages
            
            # Pool messages to target nodes
            pooled_messages = tfgnn.pool_edges_to_node(
                graph,
                edge_set_name,
                self.receiver_tag,
                reduce_type='sum',
                feature_value=weighted_messages)
            
            # Transform pooled messages
            return self.dense(pooled_messages)


    def next_state(next_state_dim, use_layer_normalization):
        return tfgnn.keras.layers.NextStateFromConcat(dense(next_state_dim, use_layer_normalization=use_layer_normalization))
    

    if not dilation:
        n_dilation_layers = 1
    
    for i in range(n_message_passing_layers):
        dil_layer_num = i % n_dilation_layers # circular usage of dilated adjacency matrices throughout message passing layers
        graph = tfgnn.keras.layers.GraphUpdate(
            node_sets = {
                "frames" : tfgnn.keras.layers.NodeSetUpdate(
                    {f"connections_{dil_layer_num}" : WeightedSumConvolution(message_dim, tfgnn.TARGET)},
                next_state(next_state_dim, use_layer_normalization)
                )
            },

            context = tfgnn.keras.layers.ContextUpdate(
                {
                    "frames" : gat_convolution(num_heads= 2, receiver_tag = tfgnn.CONTEXT)
                },
                next_state(next_state_dim, use_layer_normalization)
            
        ))(graph)



    # Get the current context state (has shape (batch_size, 128) , where 128 is the message_passing_dimension)
    # This represents the master node, which is updated in each message passing layer !
    context_state = graph.context.features['hidden_state']

    # Dropout # TODO: like in speechreco paper, see if it works/ m
  #  context_state = tf.keras.layers.Dropout(dropout_rate)(context_state)

    logits = tf.keras.layers.Dense(num_classes)(context_state)


    
    model = tf.keras.Model(input_graph, logits)

    return model 


def base_gnn_model_using_gcn(
        graph_tensor_specification,
        initial_nodes_mfccs_layer_dims = 64,
        initial_edges_weights_layer_dims = [16],
        message_dim = 128,
        next_state_dim = 128,
        num_classes = 35,
        l2_reg_factor = 6e-6,
        dropout_rate = 0.2,
        use_layer_normalization = True,
        n_message_passing_layers = 4,
        dilation = False,
        n_dilation_layers = 2,


        ):
    
    """

    # TODO 
    In this approach, instead of using SimpleConv() for the message passing, we use GCN layers!
    Note that this only works with homogeneous graphs ; therefore, we use our cosine window
    approach as it is homogeneous and use weighted edges 

    """


    # Input is the graph structure 
    input_graph = tf.keras.layers.Input(type_spec = graph_tensor_specification)

    # Convert to scalar GraphTensor
    graph = tfgnn.keras.layers.MapFeatures()(input_graph)

    is_batched = (graph.spec.rank == 1)

    if is_batched:
        batch_size = graph.shape[0]
        graph = graph.merge_batch_to_components()



    def set_initial_node_state(node_set,node_set_name):
        """
        Initialize hidden states for nodes in the graph.
        
        Args:
            node_set: A dictionary containing node features
            node_set_name: The name of the node set (e.g., "frames")
            
        Returns:
            A transformation function applied to the node features
        """
        if node_set_name == "frames":
            # Apply a dense layer to transform MFCC features into hidden states
            # Instead of just one dense layer , we can also directly use dropout etc. here (if we wish so) 
            return tf.keras.layers.Dense(initial_nodes_mfccs_layer_dims, activation="relu")(
                node_set["features"]  # This would be your mfcc_static features
            )
        else:
            # Handle any other node types
            raise ValueError(f"Unknown node set: {node_set_name}")
            
    def set_initial_edge_state(edge_set, edge_set_name):
        """
        Initialize hidden states for edges in the graph
        
        
        """
        # TODO : can be implemented if we want 
        pass 


    def set_initial_context_state():
        """
        Initialize hidden state for the context of the graph (i.e. the whole graph)
        
        """
        # TODO : can be implemented if we want
        pass
        

    graph = tfgnn.keras.layers.MapFeatures(
        node_sets_fn = set_initial_node_state, name = 'init_states')(graph)
    
    # Let us now build some basic building blocks for our model
    def dense(units, use_layer_normalization = False):
        """ Dense layer with regularization (L2 & Dropout) & normalization"""
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        result = tf.keras.Sequential([
            tf.keras.layers.Dense(
                units,
                activation = "relu",
                use_bias = True,
                kernel_regularizer = regularizer,
                bias_regularizer = regularizer),
            tf.keras.layers.Dropout(dropout_rate)])
        if use_layer_normalization:
            result.add(tf.keras.layers.LayerNormalization())
        return result 
    

    
    def gcn_convolution(message_dim, receiver_tag):
        # Here we now use a GCN layer 
        # TODO : don't understand how to add dropout ; I think
        # we would need to add it into the GCNConv class itself, since
        # we are not calling a keras layer here, but the whole class 
        # (i.e. we cannot use the sequential function like normally)
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)


        return  gcn_conv.GCNConv(
            units = message_dim,
            receiver_tag= receiver_tag,
            activation = "relu",
            use_bias = True,
            kernel_regularizer = regularizer,
            add_self_loops = False,
            edge_weight_feature_name= 'weights',
            degree_normalization= 'in'
        )

    


    # TODO : we can design our own next state function !
    def next_state(next_state_dim, use_layer_normalization):
        return tfgnn.keras.layers.NextStateFromConcat(dense(next_state_dim, use_layer_normalization=use_layer_normalization))
    

    if not dilation:
        n_dilation_layers = 1

    for i in range(n_message_passing_layers):
        dil_layer_num = i % n_dilation_layers # circular usage of dilated adjacency matrices throughout message passing layers
        graph = tfgnn.keras.layers.GraphUpdate(
            node_sets = {
                "frames" : tfgnn.keras.layers.NodeSetUpdate(
                    {f"connections_{dil_layer_num}" : (gcn_convolution(message_dim, tfgnn.SOURCE))},
                next_state(next_state_dim, use_layer_normalization)
                )
            }
        )(graph)



    pooled_features = tfgnn.keras.layers.Pool(
        tfgnn.CONTEXT, "mean", node_set_name = "frames")(graph)   # maybe mean is not the best choice, consider also sum/max
    logits = tf.keras.layers.Dense(num_classes)(pooled_features)


    
    model = tf.keras.Model(input_graph, logits)


    return model 


def base_gnn_model_using_gcn_with_residual_blocks(
        graph_tensor_specification,
        initial_nodes_mfccs_layer_dims=128,
        message_dim=128,
        next_state_dim=128,
        skip_connection_type=None,
        num_classes=35,
        l2_reg_factor=6e-6,
        dropout_rate=0.2,
        use_layer_normalization=True,
        n_message_passing_layers=4,
        ):
    
    # Input is the graph structure 
    input_graph = tf.keras.layers.Input(type_spec=graph_tensor_specification)

    # Convert to scalar GraphTensor
    graph = tfgnn.keras.layers.MapFeatures()(input_graph)

    is_batched = (graph.spec.rank == 1)
    if is_batched:
        batch_size = graph.shape[0]
        graph = graph.merge_batch_to_components()

    # Initialize node states
    def set_initial_node_state(node_set, node_set_name):
        if node_set_name == "frames":
            return tf.keras.layers.Dense(initial_nodes_mfccs_layer_dims, activation="relu")(
                node_set["features"]  
            )
        else:
            raise ValueError(f"Unknown node set: {node_set_name}")

    graph = tfgnn.keras.layers.MapFeatures(
        node_sets_fn=set_initial_node_state, name='init_states')(graph)
    
    # Define layer building blocks
    def dense(units, use_layer_normalization=False):
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        result = tf.keras.Sequential([
            tf.keras.layers.Dense(
                units,
                activation="relu",
                use_bias=True,
                kernel_regularizer=regularizer,
                bias_regularizer=regularizer),
            tf.keras.layers.Dropout(dropout_rate)
        ])
        if use_layer_normalization:
            result.add(tf.keras.layers.LayerNormalization())
        return result 
    
    def gcn_convolution(message_dim, receiver_tag):
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        return gcn_conv.GCNConv(
            units=message_dim,
            receiver_tag=receiver_tag,
            activation="relu",
            use_bias=True,
            kernel_regularizer=regularizer,
            add_self_loops=False,
            edge_weight_feature_name="weights",
            degree_normalization="in"
        )

    # Create a residual block as a custom keras model
    class GCNResidualBlock(tf.keras.Model):
        def __init__(self, message_dim, next_state_dim, use_layer_normalization):
            super().__init__()
            # First GCN layer and state update
            self.gcn1 = gcn_convolution(message_dim, tfgnn.SOURCE)
            self.next_state1 = tfgnn.keras.layers.NextStateFromConcat(
                dense(next_state_dim, use_layer_normalization))
            
            # Graph update layer
            self.graph_update = tfgnn.keras.layers.GraphUpdate(
                node_sets={
                    "frames": tfgnn.keras.layers.NodeSetUpdate(
                        {"connections": (self.gcn1)},
                        self.next_state1
                    )
                }
            )
        
        def call(self, inputs):
            # Process the graph through the GCN
            outputs = self.graph_update(inputs)
            
            # Apply the residual connection if needed
            if skip_connection_type == 'sum':
                # Extract the node states from input and output graphs
                input_state = inputs.node_sets["frames"]["hidden_state"]
                output_state = outputs.node_sets["frames"]["hidden_state"]
                
                # Create a new graph with the residual connection
                result = tfgnn.GraphTensor.from_pieces(
                    context=outputs.context,
                    node_sets={
                        "frames": tfgnn.NodeSet.from_fields(
                            sizes=outputs.node_sets["frames"].sizes,
                            features={
                                **outputs.node_sets["frames"].features,
                                "hidden_state": input_state + output_state
                            }
                        )
                    },
                    edge_sets=outputs.edge_sets
                )
                return result
            
            return outputs
    
    # Process graph through residual blocks
    for i in range(n_message_passing_layers):
        # Create and apply a residual block
        block = GCNResidualBlock(
            message_dim=message_dim,
            next_state_dim=next_state_dim,
            use_layer_normalization=use_layer_normalization
        )
        
        # Skip connection in the first layer doesn't make sense
        if i == 0:
            # For the first layer, just apply the GCN without residual
            graph = tfgnn.keras.layers.GraphUpdate(
                node_sets={
                    "frames": tfgnn.keras.layers.NodeSetUpdate(
                        {"connections": (gcn_convolution(message_dim, tfgnn.SOURCE))},
                        tfgnn.keras.layers.NextStateFromConcat(dense(next_state_dim, use_layer_normalization))
                    )
                }
            )(graph)
        else:
            # For subsequent layers, use the residual block
            graph = block(graph)
    
    # Final pooling and classification
    pooled_features = tfgnn.keras.layers.Pool(
        tfgnn.CONTEXT, "sum", node_set_name="frames")(graph)
    
    # Add a final classifier layer
    logits = tf.keras.layers.Dense(num_classes)(pooled_features)
    
    # Create the model
    model = tf.keras.Model(input_graph, logits)
    
    return model


def base_gnn_with_context_node_model(
        graph_tensor_specification,
        initial_nodes_mfccs_layer_dims = 64,
        initial_edges_weights_layer_dims = [16],
        message_dim = 128,
        next_state_dim = 128,
        num_classes = 35,
        l2_reg_factor = 6e-6,
        dropout_rate = 0.2,
        use_layer_normalization = True,
        n_message_passing_layers = 4,
        dilation = False,
        n_dilation_layers = 2,


        ):
    
    """

    Here, we additionally add a context node ("Master node") to the graph, which is used to aggregate information from all nodes.
    In the Base GNN model, we simply aggregated the final information for the master node representation. Here, we aim to
    aggregate the context in every message passing layer.


    This section discusses the use of a context feature for a hidden state that gets updated with each GraphUpdate.

    Why would you do that?

    If your task is a prediction about the whole graph, a context state that represents the relevant properties of the graph is a plausible input to the prediction 
    head of your model. Maintaining that state throughout the GNN is potentially more expressive than a single pooling of node states at the end of the GNN.
    A context state that gets fed back into node state updates could condition them on some global characteristics of the graph.



    """

    # Input is the graph structure 
    input_graph = tf.keras.layers.Input(type_spec = graph_tensor_specification)


    # Convert to scalar GraphTensor
    graph = tfgnn.keras.layers.MapFeatures()(input_graph)

    is_batched = (graph.spec.rank == 1)

    if is_batched:
        batch_size = graph.shape[0]
        graph = graph.merge_batch_to_components()
        


    # Define the initial hidden states for the nodes
    def set_initial_node_state(node_set,node_set_name):
        """
        Initialize hidden states for nodes in the graph.
        
        Args:
            node_set: A dictionary containing node features
            node_set_name: The name of the node set (e.g., "frames")
            
        Returns:
            A transformation function applied to the node features
        """
        if node_set_name == "frames":
            # Apply a dense layer to transform MFCC features into hidden states
            # Instead of just one dense layer , we can also directly use dropout etc. here (if we wish so) 
            return tf.keras.layers.Dense(initial_nodes_mfccs_layer_dims, activation="relu")(
                node_set["features"]  # This would be your mfcc_static features
            )
        else:
            # Handle any other node types
            raise ValueError(f"Unknown node set: {node_set_name}")
            
    def set_initial_edge_state(edge_set, edge_set_name):
        """
        Initialize hidden states for edges in the graph
        
        
        """
        # TODO : can be implemented if we want 
        pass 


    def set_initial_context_state(context):
        """
        Initialize hidden state for the context of the graph (i.e. the whole graph)
        
        """

        # Option 1 : initialize the context node with a zero vector
        return tfgnn.keras.layers.MakeEmptyFeature()(context)

    
        
        # Option 2: Initialize with a pooled representation of all nodes (in their initial state)
     #   pooled = tfgnn.keras.layers.Pool(
     #       tfgnn.CONTEXT, "mean", node_set_name="frames")(graph)
     #   return tf.keras.layers.Dense(next_state_dim, activation="relu")(pooled)
        

    graph = tfgnn.keras.layers.MapFeatures(
        node_sets_fn = set_initial_node_state,
        context_fn = set_initial_context_state, name = 'init_states')(graph) # added initial context state 
    
    # Let us now build some basic building blocks for our model
    def dense(units, use_layer_normalization = False):
        """ Dense layer with regularization (L2 & Dropout) & normalization"""
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        result = tf.keras.Sequential([
            tf.keras.layers.Dense(
                units,
                activation = "relu",
                use_bias = True,
                kernel_regularizer = regularizer,
                bias_regularizer = regularizer),
            tf.keras.layers.Dropout(dropout_rate)])
        if use_layer_normalization:
            result.add(tf.keras.layers.LayerNormalization())
        return result 
    

    def convolution(message_dim, receiver_tag):
        return tfgnn.keras.layers.SimpleConv(dense(message_dim), "sum", receiver_tag = receiver_tag)
    

    
    #TODO: With edge weights
    def convolution_with_weights(message_dim, receiver_tag):
        pass


    def next_state(next_state_dim, use_layer_normalization):
        return tfgnn.keras.layers.NextStateFromConcat(dense(next_state_dim, use_layer_normalization=use_layer_normalization))
    

    if not dilation:
        n_dilation_layers = 1
    
    # after the first message passing layer, nodes are (3136,128) and context node is (32,128)
    for i in range(n_message_passing_layers):
        dil_layer_num = i % n_dilation_layers # circular usage of dilated adjacency matrices throughout message passing layers
        graph = tfgnn.keras.layers.GraphUpdate(
            node_sets = {
                "frames" : tfgnn.keras.layers.NodeSetUpdate(
                    {f"connections_{dil_layer_num}" : convolution(message_dim, tfgnn.SOURCE)},
                next_state(next_state_dim, use_layer_normalization)
                )
            },
            # Here we just do an easy implementation : in each message passing layer, take all the current node features
            # and pool them using the mean
            context = tfgnn.keras.layers.ContextUpdate(
                {
                    "frames" : tfgnn.keras.layers.Pool(tfgnn.CONTEXT, "mean", node_set_name = "frames")
                },
                next_state(next_state_dim, use_layer_normalization)
            
        ))(graph)



    # Get the current context state (has shape (batch_size, 128) , where 128 is the message_passing_dimension)
    # This represents the master node, which is updated in each message passing layer !
    context_state = graph.context.features['hidden_state']

    logits = tf.keras.layers.Dense(num_classes)(context_state)


    
    model = tf.keras.Model(input_graph, logits)


    return model 


def base_gnn_weighted_model(
        graph_tensor_specification,
        initial_nodes_mfccs_layer_dims = 64,
        initial_edges_weights_layer_dims = [16],
        message_dim = 128,
        next_state_dim = 128,
        num_classes = 35,
        l2_reg_factor = 6e-6,
        dropout_rate = 0.2,
        use_layer_normalization = True,
        n_message_passing_layers = 4,
        dilation = False,
        n_dilation_layers = 2,


        ):
    

    """
    
    Using the weighted edges + also a new initial node state encoding ;
    in the end use pooling with max for context node
    
    """
    

    # Input is the graph structure 
    input_graph = tf.keras.layers.Input(type_spec = graph_tensor_specification)

    # Convert to scalar GraphTensor
    graph = tfgnn.keras.layers.MapFeatures()(input_graph)

    is_batched = (graph.spec.rank == 1)

    if is_batched:
        batch_size = graph.shape[0]
        graph = graph.merge_batch_to_components()


    # Define the initial hidden states for the nodes
    def set_initial_node_state(node_set,node_set_name):
        """
        Initialize hidden states for nodes in the graph.
        
        Args:
            node_set: A dictionary containing node features
            node_set_name: The name of the node set (e.g., "frames")
            
        Returns:
            A transformation function applied to the node features
        """


        def dense_inner(units, use_layer_normalization = False, normalization_type = "normal"):
            regularizer = tf.keras.regularizers.l2(l2_reg_factor)
            result = tf.keras.Sequential([
                tf.keras.layers.Dense(
                    units,
                    activation = "relu",
                    use_bias = True,
                    kernel_regularizer = regularizer,
                    bias_regularizer = regularizer),
                tf.keras.layers.Dropout(dropout_rate)])
            if use_layer_normalization:
                if normalization_type == 'normal':
                    result.add(tf.keras.layers.LayerNormalization())
                elif normalization_type == 'group':
                    result.add(tf.keras.layers.GroupNormalization(message_dim))
            return result 


        if node_set_name == "frames":


            features = node_set["features"]

            # Split the diff. features such that we can do separate layer learning


            # TODO : try to do base mfcc + its energy, delta + energy, delta-delta + energy
            base_mfccs = features[: , 0:12]
            delta_mfccs = features[: , 12:24]
            delta_delta_mfccs = features[:, 24:36]
            energy_features = features[:, 36:39]

            base_processed = dense_inner(24, use_layer_normalization=True)(base_mfccs)
            delta_processed = dense_inner(24, use_layer_normalization=True)(delta_mfccs)
            delta_delta_processed = dense_inner(24, use_layer_normalization=True)(delta_delta_mfccs)
            energy_processed = dense_inner(8, use_layer_normalization=True)(energy_features)

            # Concatenate the processed features
            combined_features = tf.keras.layers.Concatenate()(
                [base_processed, delta_processed, delta_delta_processed, energy_processed]
            )
            


            return dense_inner(initial_nodes_mfccs_layer_dims, use_layer_normalization=True)(combined_features)
            
        else:
            # Handle any other node types
            raise ValueError(f"Unknown node set: {node_set_name}")
        
            
    def set_initial_edge_state(edge_set, edge_set_name):
        """
        Initialize hidden states for edges in the graph
        
        
        """
        # TODO : I need it to be able to use the weights of the edges in the convolution_with_weights function
        pass 


    def set_initial_context_state():
        """
        Initialize hidden state for the context of the graph (i.e. the whole graph)
        
        """
        # TODO : can be implemented if we want
        pass


        

    graph = tfgnn.keras.layers.MapFeatures(
        node_sets_fn = set_initial_node_state, name = 'init_states')(graph)
    

    
    # Let us now build some basic building blocks for our model
    def dense(units, use_layer_normalization = False, normalization_type = "normal"):
        """ Dense layer with regularization (L2 & Dropout) & normalization"""
        regularizer = tf.keras.regularizers.l2(l2_reg_factor)
        result = tf.keras.Sequential([
            tf.keras.layers.Dense(
                units,
                activation = "relu",
                use_bias = True,
                kernel_regularizer = regularizer,
                bias_regularizer = regularizer),
            tf.keras.layers.Dropout(dropout_rate)])
        if use_layer_normalization:
            if normalization_type == 'normal':
                result.add(tf.keras.layers.LayerNormalization())
            elif normalization_type == 'group':
                result.add(tf.keras.layers.GroupNormalization(message_dim))
        return result 
    


    

    # Message passing with edge weights

    # Define a custom class object for the weighted convolution
    # This class will inherit from tf.keras.layers.AnyToAnyConvolutionBase
    


    class WeightedSumConvolution(tf.keras.layers.Layer):

        def __init__(self, message_dim, receiver_tag):
            super().__init__()
            self.message_dim = message_dim
            self.receiver_tag = receiver_tag
            self.sender_tag = tfgnn.SOURCE if receiver_tag == tfgnn.TARGET else tfgnn.TARGET
            self.dense = dense(units = message_dim, use_layer_normalization = use_layer_normalization)
        
        def call(self, graph, edge_set_name):
            # Get node states
            messages = tfgnn.broadcast_node_to_edges(
                graph,
                edge_set_name,
                self.sender_tag,
                feature_name="hidden_state") # Take the hidden state of the node
            
            # Get edge weights
            weights = graph.edge_sets[edge_set_name].features['weights']
            
            # Apply weights to messages
            weighted_messages = tf.expand_dims(weights, -1) * messages
            
            # Pool messages to target nodes
            pooled_messages = tfgnn.pool_edges_to_node(
                graph,
                edge_set_name,
                self.receiver_tag,
                reduce_type='sum',
                feature_value=weighted_messages)
            
            # Transform pooled messages
            return self.dense(pooled_messages)
            
    

    #TODO: Else we can try to define a reduce_type(messages, adjacency_matrix) function that gives back the weighted sum of the messages with the edge weights
    # We just need to access the node index and collect the neighbors of the node and then we can multiply the messages with the weights of the edges
    



    def next_state(next_state_dim, use_layer_normalization):
        return tfgnn.keras.layers.NextStateFromConcat(dense(next_state_dim, use_layer_normalization=use_layer_normalization))
    
    if not dilation:
        n_dilation_layers = 1

    for i in range(n_message_passing_layers):
        dil_layer_num = i % n_dilation_layers # circular usage of dilated adjacency matrices throughout message passing layers
        graph = tfgnn.keras.layers.GraphUpdate(
            node_sets = {
                "frames" : tfgnn.keras.layers.NodeSetUpdate(
                    {f"connections_{dil_layer_num}" : WeightedSumConvolution(message_dim, tfgnn.TARGET)},
                next_state(next_state_dim, use_layer_normalization)
                )
            }
        )(graph)



    pooled_features = tfgnn.keras.layers.Pool(
        tfgnn.CONTEXT, "max", node_set_name = "frames")(graph)   
    logits = tf.keras.layers.Dense(num_classes)(pooled_features)


    
    model = tf.keras.Model(input_graph, logits)


    return model 






# NOTE: 
# This model is just to see if my ATTENTION WEIGHTS are correctly detecting the important parts of the audio signal

def extract_attention(base_model):
    """
    Creates a model that outputs attention weights for visualization
    """
    # Create a new model to extract attention weights from base_model
    # First, get access to the GATv2Conv layers in your model
    gatv2_layers = []
    
    # Find all GATv2Conv layers in the model
    def find_gatv2_layers(model):
        gatv2_layers = []
        
        # Recursively search through layers
        def search_layers(layer):
            if isinstance(layer, GATv2Conv):
                gatv2_layers.append(layer)
            
            # If the layer has sublayers, search through them
            if hasattr(layer, 'layers'):
                for sublayer in layer.layers:
                    search_layers(sublayer)
        
        # Start the search
        for layer in model.layers:
            search_layers(layer)
        
        return gatv2_layers

    # Find the GATv2Conv layers
    gatv2_layers = find_gatv2_layers(base_model)
    
    # Define a custom model to extract attention weights
    class AttentionExtractionModel(tf.keras.Model):
        def __init__(self, base_model, gatv2_layers):
            super().__init__()
            self.base_model = base_model
            self.gatv2_layers = gatv2_layers
            
        def call(self, inputs):
            # First do a forward pass to make sure all layers are computed
            _ = self.base_model(inputs)
            
            # Now try to extract attention weights from each GATv2Conv layer
            attention_weights = []
            for layer in self.gatv2_layers:
                # This is a simplification - the actual attribute name may vary
                # depending on your GATv2Conv implementation
                if hasattr(layer, '_attention_weights'):
                    attention_weights.append(layer._attention_weights)
                elif hasattr(layer, 'attention_weights'):
                    attention_weights.append(layer.attention_weights)
            
            return attention_weights
    
    attention_model = AttentionExtractionModel(base_model, gatv2_layers)
    
    return attention_model





def train(model, train_ds, val_ds, test_ds, epochs = 50, batch_size = 32, use_callbacks = True, learning_rate = 0.001):

    # Define callbacks
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor='val_sparse_categorical_accuracy',
            patience=10,
            restore_best_weights=True
        ),
     #   tf.keras.callbacks.ReduceLROnPlateau(
     #       monitor='val_loss',
     #       factor=0.5,
     #       patience=5,
     #       min_lr=1e-5
     #   )
    ]


    model.compile(
        # legacy due to running on mac m1
        optimizer = tf.keras.optimizers.legacy.Adam(learning_rate = learning_rate),
        # using sparse categorical bc our labels are encoded as numbers and not one-hot
        loss = tf.keras.losses.SparseCategoricalCrossentropy(from_logits = True),
        metrics = [tf.keras.metrics.SparseCategoricalAccuracy()],
       # run_eagerly = True
    )


    if use_callbacks:
        history = model.fit(train_ds, validation_data = val_ds, epochs = epochs, callbacks = callbacks)
    else:
        history = model.fit(train_ds, validation_data = val_ds, epochs = epochs)


    # Evaluate the model
    test_measurements = model.evaluate(test_ds)


    print(f"Test Loss : {test_measurements[0]:.2f},\
          Test Sparse Categorical Accuracy : {test_measurements[1]:.2f}")




    return history
