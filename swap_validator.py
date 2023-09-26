from pathlib import Path

from casper_node_ssh import NodeSet

LOCAL_UNIT_STORE = Path("unit_files").absolute()

if not LOCAL_UNIT_STORE.exists():
    raise Exception(f"{LOCAL_UNIT_STORE} does not exist.")


SSH_NODE_NAMES = ["joe-inttest", "joe-inttest2"]

nodeset = NodeSet.from_servers(SSH_NODE_NAMES)
if nodeset.pre_swap_checks():
    nodeset.swap(LOCAL_UNIT_STORE)
