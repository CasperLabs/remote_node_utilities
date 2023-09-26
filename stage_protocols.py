from casper_node_ssh import Node


MY_SERVERS = ["node_a", "node_b", "node_c"]

for server in MY_SERVERS:
    node = Node(server)
    node.stage_protocols()
