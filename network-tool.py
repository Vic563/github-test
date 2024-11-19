import getpass
import paramiko
import logging
import time
import re
from datetime import datetime, timedelta
import pytz
import sched

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DeviceCommands:
    """Class to handle vendor-specific commands"""
    
    @staticmethod
    def get_pagination_command(device_type):
        commands = {
            'juniper': 'set cli screen-length 0',
            'cisco-ios': 'terminal length 0',
            'cisco-nxos': 'terminal length 0',
            'arista': 'terminal length 0',
            'default': 'terminal length 0'
        }
        return commands.get(device_type, commands['default'])
    
    @staticmethod
    def get_config_mode_command(device_type):
        commands = {
            'juniper': 'configure',
            'cisco-ios': 'configure terminal',
            'cisco-nxos': 'configure terminal',
            'arista': 'configure terminal',
            'default': 'configure terminal'
        }
        return commands.get(device_type, commands['default'])
    
    @staticmethod
    def get_commit_command(device_type):
        commands = {
            'juniper': 'commit and-quit',
            'cisco-ios': 'end',
            'cisco-nxos': 'end',
            'arista': 'end',
            'default': 'end'
        }
        return commands.get(device_type, commands['default'])

def get_user_input():
    hostnames = input("Enter hostname(s) or IP address(es) (separated by commas): ")
    hostname_list = [h.strip() for h in hostnames.split(',')]
    username = input("Enter username: ")
    password = getpass.getpass(prompt='Enter password: ')
    return hostname_list, username, password

def get_commands():
    print("Enter commands to execute. Press Enter once when finished:")
    commands = []
    while True:
        command = input()
        if command == '':
            break
        commands.append(command)
    return commands

def get_schedule_option():
    option = input("Do you want to schedule the config push? (yes/no): ").strip().lower()
    if option in ['yes', 'y']:
        date_str = input("Enter date and time in EST (YYYY-MM-DD HH:MM:SS): ").strip()
        est = pytz.timezone('US/Eastern')
        scheduled_time = est.localize(datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S"))
        return scheduled_time
    return None

def identify_device_type(shell):
    """Identify the network device type and model."""
    shell.settimeout(2)
    
    # First try Juniper identification
    shell.send('set cli screen-length 0\n')
    time.sleep(1)
    output = shell.recv(1024).decode('utf-8', errors='ignore')
    
    if 'syntax error' not in output.lower():
        # It's a Juniper device
        shell.send('show version\n')
        time.sleep(2)
        version_output = get_command_output(shell)
        
        # Parse Juniper model
        match = re.search(r'^Model:\s*(\S+)', version_output, re.MULTILINE)
        if match:
            model = match.group(1).lower()
            if 'mx' in model:
                return 'juniper-mx'
            elif 'ex' in model:
                return 'juniper-ex'
            elif 'srx' in model:
                return 'juniper-srx'
            elif 'qfx' in model:
                return 'juniper-qfx'
            else:
                return 'juniper-unknown'
    
    # Try Cisco/Arista identification
    shell.send('terminal length 0\n')
    time.sleep(1)
    shell.recv(1024)  # Clear buffer
    
    shell.send('show version\n')
    time.sleep(2)
    version_output = get_command_output(shell)
    
    # Cisco IOS/IOS-XE detection
    if re.search(r'cisco ios|ios software', version_output, re.IGNORECASE):
        # Detect specific Cisco models
        if re.search(r'ASR\d+', version_output):
            return 'cisco-ios-asr'
        elif re.search(r'ISR\d+', version_output):
            return 'cisco-ios-isr'
        elif re.search(r'CSR\d+', version_output):
            return 'cisco-ios-csr'
        elif re.search(r'C\d+', version_output):  # Catalyst switches
            return 'cisco-ios-catalyst'
        else:
            return 'cisco-ios'
    
    # Cisco NX-OS detection
    elif re.search(r'nx-os|nexus', version_output, re.IGNORECASE):
        if re.search(r'N[1-9][K]', version_output):  # Nexus series
            return 'cisco-nxos'
        else:
            return 'cisco-nxos-unknown'
    
    # Arista detection
    elif re.search(r'arista', version_output, re.IGNORECASE):
        if re.search(r'DCS-\d+', version_output):
            return 'arista-dcs'
        else:
            return 'arista'
    
    return 'unknown'

def get_command_output(shell, timeout=2):
    """Get command output with timeout."""
    output = ''
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            if shell.recv_ready():
                recv_data = shell.recv(4096).decode('utf-8', errors='ignore')
                if not recv_data:
                    break
                output += recv_data
            else:
                time.sleep(0.1)
        except Exception:
            break
    return output

def execute_commands(shell, commands, device_type):
    """Execute commands based on device type with improved handling."""
    shell.settimeout(2)
    output_data = ''
    
    # Set pagination off based on device type
    pagination_cmd = DeviceCommands.get_pagination_command(device_type)
    shell.send(pagination_cmd + '\n')
    time.sleep(1)
    shell.recv(1024)  # Clear buffer
    
    # Enter configuration mode if needed
    if any(cmd.strip().lower().startswith(('set', 'conf')) for cmd in commands):
        config_cmd = DeviceCommands.get_config_mode_command(device_type)
        shell.send(config_cmd + '\n')
        time.sleep(1)
        shell.recv(1024)  # Clear buffer
    
    # Execute each command
    for command in commands:
        shell.send(command + '\n')
        time.sleep(1)
        output_data += get_command_output(shell)
    
    # Exit configuration mode if needed
    if any(cmd.strip().lower().startswith(('set', 'conf')) for cmd in commands):
        commit_cmd = DeviceCommands.get_commit_command(device_type)
        shell.send(commit_cmd + '\n')
        time.sleep(1)
        output_data += get_command_output(shell)
    
    return output_data

def perform_pre_post_checks(hostname_list, username, password, commands, check_type):
    for hostname in hostname_list:
        hostname = hostname.strip()
        try:
            logging.info("Connecting to %s for %s checks", hostname, check_type)
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname, username=username, password=password, allow_agent=False, look_for_keys=False)
            logging.info("Connected to %s", hostname)

            shell = client.invoke_shell()
            time.sleep(1)

            device_type = identify_device_type(shell)
            logging.info(f"Detected device type: {device_type}")

            output = execute_commands(shell, commands, device_type)
            save_option = input(f"Do you want to save the {check_type} check output to a file? (yes/no): ").strip().lower()
            if save_option in ['yes', 'y']:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                default_filename = f"{hostname}_{check_type}_{timestamp}.txt"
                file_path = input(f"Enter the file path to save the output [{default_filename}]: ").strip()
                if not file_path:
                    file_path = default_filename
                with open(file_path, 'w') as file:
                    file.write(f"Output from {hostname} ({device_type}):\n{output}\n")
                logging.info(f"Output saved to {file_path}")
            else:
                print(f"Output from {hostname} ({device_type}):\n{output}")

            shell.close()
            client.close()
            logging.info("Disconnected from %s", hostname)
        except Exception as e:
            logging.error("An error occurred with %s: %s", hostname, str(e))

def config_push(hostname_list, username, password, commands):
    for hostname in hostname_list:
        hostname = hostname.strip()
        try:
            logging.info("Connecting to %s", hostname)
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname, username=username, password=password, allow_agent=False, look_for_keys=False)
            logging.info("Connected to %s", hostname)

            shell = client.invoke_shell()
            time.sleep(1)

            device_type = identify_device_type(shell)
            logging.info(f"Detected device type: {device_type}")

            output = execute_commands(shell, commands, device_type)
            print(f"Output from {hostname} ({device_type}):\n{output}")

            shell.close()
            client.close()
            logging.info("Disconnected from %s", hostname)
        except Exception as e:
            logging.error("An error occurred with %s: %s", hostname, str(e))

def main():
    hostname_list, username, password = get_user_input()
    option = input("Select an option:\n1. Config Push\n2. Pre-checks\n3. Post-checks\nEnter your choice: ").strip()
    
    if option == '1':
        commands = get_commands()
        scheduled_time = get_schedule_option()

        if scheduled_time:
            now = datetime.now(pytz.timezone('US/Eastern'))
            delay = (scheduled_time - now).total_seconds()
            scheduler = sched.scheduler(time.time, time.sleep)
            scheduler.enter(delay, 1, config_push, (hostname_list, username, password, commands))
            logging.info("Scheduled config push at %s", scheduled_time)
            scheduler.run()
        else:
            config_push(hostname_list, username, password, commands)
    elif option == '2':
        commands = get_commands()
        perform_pre_post_checks(hostname_list, username, password, commands, "pre-check")
    elif option == '3':
        commands = get_commands()
        perform_pre_post_checks(hostname_list, username, password, commands, "post-check")
    else:
        logging.error("Invalid option selected. Exiting.")

if __name__ == "__main__":
    main()
