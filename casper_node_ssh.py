import subprocess
import os
from dataclasses import dataclass
import glob
import json
from typing import Optional

KEY_FILES = ["public_key_hex", "public_key.pem", "secret_key.pem"]


@dataclass
class Node:
    ssh_host: str
    key_base_dir: str = "/etc/casper/validator_keys"
    validator_key_dir: str = "/etc/casper/validator_keys/current_node"
    offline_key_dir: str = "/etc/casper/validator_keys/backup_node"
    _status: Optional[dict] = None

    def __repr__(self):
        return self.ssh_host

    def ssh_command(self, shell_command):
        command = f"ssh {self.ssh_host} {shell_command}"
        print(command)
        response = subprocess.Popen(command,
                                    shell=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE).communicate()
        if response[1] != b'':
            raise Exception(f"Error from ssh command: {shell_command}\n{response[1].decode('utf-8')}")
        return response[0].decode('utf-8')

    def keys_to_validator(self):
        command = f"sudo -u casper cp {self.validator_key_dir}/* {self.key_base_dir}/"
        self.ssh_command(command)

    def keys_to_offline(self):
        command = f"sudo -u casper cp {self.offline_key_dir}/* {self.key_base_dir}/"
        self.ssh_command(command)

    @property
    def is_validator(self):
        command = f"diff {self.validator_key_dir}/{KEY_FILES[0]} {self.key_base_dir}/{KEY_FILES[0]}"
        response = self.ssh_command(command)
        return response == ''

    def remote_file_exists(self, remote_file: str):
        response = self.ssh_command(f'\'FILE={remote_file}; sudo [ -e "$FILE" ] && echo "exists";\'')
        return response.strip() == 'exists'

    def missing_key_files(self):
        missing = []
        for file_name in KEY_FILES:
            file_path = f"{self.validator_key_dir}/{file_name}"
            if not self.remote_file_exists(file_path):
                missing.append(file_path)
            file_path = f"{self.offline_key_dir}/{file_name}"
            if not self.remote_file_exists(file_path):
                missing.append(file_path)
        return missing

    def rest_status(self, refresh=False):
        if refresh or self._status is None:
            response = self.ssh_command("'curl -s localhost:8888/status'")
            self._status = json.loads(response)
        return self._status

    @property
    def network_name(self):
        network_name = self.rest_status().get("chainspec_name")
        if network_name is None:
            raise Exception("Cannot retrieve chainspec_name from status.")
        return network_name

    @property
    def reactor_state(self):
        return self.rest_status().get("reactor_state")

    def stop_node(self):
        self.ssh_command("sudo /etc/casper/node_util.py stop")

    def start_node(self):
        self.ssh_command("sudo /etc/casper/node_util.py start")

    def systemd_status(self):
        return self.ssh_command("/etc/casper/node_util.py systemd_status")

    def stage_protocols(self):
        return self.ssh_command(f"sudo -u casper /etc/casper/node_util.py stage_protocols {self.network_name()}.conf")

    @property
    def remote_unit_file_location(self):
        return f"/var/lib/casper/casper-node/{self.network_name}/unit_files"

    def get_unit_files(self, local_unit_dir: str):
        # clean local unit_files
        for f in glob.glob(f"{local_unit_dir}/*"):
            os.remove(f)
        command = f"rsync -avx {self.ssh_host}:{self.remote_unit_file_location}/* {local_unit_dir}/"
        print(command)
        response = subprocess.Popen(command,
                                    shell=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE).communicate()
        if response[1] != b'':
            raise Exception(f"Error from rsync command: {command}\n{response[1]}")
        print(response[0].decode('utf-8'))

    def put_unit_files(self, local_unit_dir: str):
        # Needs casper user to save...

        response = self.ssh_command("mktemp -d")
        remote_location = response.strip()
        print(f"Created temp folder for sync: {remote_location}")
        command = f"rsync -avx {local_unit_dir}/* {self.ssh_host}:{remote_location}/"
        print(command)
        response = subprocess.Popen(command,
                                    shell=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE).communicate()
        if response[1] != b'':
            raise Exception(f"Error from rsync command: {command}\n{response[1]}")
        print(response[0].decode('utf-8'))

        print(f"Moving to correct location as casper user...")
        self.ssh_command(f"sudo mv {remote_location}/* {self.remote_unit_file_location}/")

        print(f"Fixing permissions...")
        self.ssh_command(f"sudo /etc/casper/node_util.py fix_permissions")

        print(f"Removing temp folder: {remote_location}...")
        self.ssh_command(f"sudo rmdir {remote_location}")


@dataclass()
class NodeSet:
    node_a: Node
    node_b: Node
    _validator: Optional[Node] = None

    @staticmethod
    def from_servers(servers):
        if len(servers) != 2:
            raise Exception("Expected 2 servers for node swap.")
        return NodeSet(Node(servers[0]), Node(servers[1]))

    @property
    def validator(self):
        if self._validator is None:
            node_a_val = self.node_a.is_validator
            node_b_val = self.node_b.is_validator
            if node_a_val and node_b_val:
                raise Exception(f"Both {self.node_a.ssh_host} and {self.node_b.ssh_host} indicate as validator. This is bad.")
            elif node_a_val:
                self._validator = self.node_a
            elif node_b_val:
                self._validator = self.node_b
            else:
                raise Exception("No nodes are validator, something is wrong.")
        return self._validator

    @property
    def non_validator(self):
        if self.node_a is self.validator:
            return self.node_b
        return self.node_a

    def _check_reactor_state(self, node: Node, expected_state: str):
        if node.reactor_state != expected_state:
            return f"Expected {self.validator} to have reactor_state of " \
                   f"{expected_state} not {self.validator.reactor_state}."
        print(f"{node} in reactor_state of {expected_state}")

    def pre_swap_checks(self):
        errors = []
        # Check network compatibility
        if self.validator.network_name != self.non_validator.network_name:
            errors.append(f"{self.validator} is on network: {self.validator.network_name}\n"
                          f"{self.non_validator} is on network: {self.non_validator.network_name}")
        else:
            print("On same networks...")

        # Check validator at tip
        response = self._check_reactor_state(self.validator, "Validate")
        if response:
            errors.append(response)

        # Check non-validator at tip
        response = self._check_reactor_state(self.non_validator, "KeepUp")
        if response:
            errors.append(response)

        # Test val and off dirs on both servers
        missing = self.validator.missing_key_files()
        for miss in missing:
            errors.append(f"Missing source key file on {self.validator}: {miss}")

        missing = self.non_validator.missing_key_files()
        for miss in missing:
            errors.append(f"Missing source key file on {self.non_validator}: {miss}")

        if errors:
            print("Errors encountered:")
            print("\n".join(errors))
            return False
        print("All checks complete")
        return True

    def swap(self, local_unit_dir: str):
        # Verify status is loaded for both
        self.validator.rest_status()
        self.non_validator.rest_status()
        print(f"Stopping Validator {self.validator}...")
        self.validator.stop_node()

        print(f"Getting unit_files from {self.validator}...")
        self.validator.get_unit_files(local_unit_dir)

        print(f"Putting unit_file on {self.non_validator}...")
        self.non_validator.put_unit_files(local_unit_dir)

        print(f"Stopping Non-Validator {self.non_validator}...")
        self.non_validator.stop_node()

        print(f"Swapping keys to Validator on {self.non_validator}...")
        self.non_validator.keys_to_validator()

        print(f"Starting {self.non_validator}...")
        self.non_validator.start_node()

        print(f"Swapping keys to Offline on {self.validator}...")
        self.validator.keys_to_offline()

        print(f"Starting {self.validator}...")
        self.validator.start_node()

        print(f"Status of new validator:")
        self.non_validator.systemd_status()

        # Reset what is known as validator
        self._validator = None

