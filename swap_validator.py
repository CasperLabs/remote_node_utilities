from pathlib import Path

from casper_node_ssh import NodeSet

# This is a local path where you store unit files when transferring between servers
LOCAL_UNIT_STORE = Path("unit_files").absolute()

if not LOCAL_UNIT_STORE.exists():
    raise Exception(f"{LOCAL_UNIT_STORE} does not exist.")

# This should be the name if servers you have defined in your ~/.ssh/config such that connecting to them
# with `ssh [name]` is valid.
SSH_NODE_NAMES = ["joe-inttest", "joe-inttest2"]

nodeset = NodeSet.from_servers(SSH_NODE_NAMES)
if nodeset.pre_swap_checks():
    print("here we go!")
    # Only uncomment below when you have tested things and are ready to swap
    #nodeset.swap(LOCAL_UNIT_STORE)

