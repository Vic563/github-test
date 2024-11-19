import getpass
import paramiko
import logging
import time
import re
from datetime import datetime, timedelta
import pytz
import sched
import difflib
from collections import defaultdict

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

def get_all_commands():
    """Get config, pre-check, and post-check commands separately."""
    print("Enter configuration commands to execute. Press Enter twice when finished:")
    config_commands = get_commands()
    
    print("\nEnter pre-check commands. Press Enter twice when finished:")
    pre_check_commands = get_commands()
    
    print("\nEnter post-check commands (or press Enter to use the same as pre-check):")
    post_check_commands = get_commands()
    if not post_check_commands:
        post_check_commands = pre_check_commands
    
    return config_commands, pre_check_commands, post_check_commands

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

def compare_outputs(pre_output, post_output, hostname):
    """Compare pre and post check outputs and generate detailed diff."""
    def clean_output(output):
        # Remove timestamp variations and other volatile data
        lines = output.splitlines()
        cleaned = []
        for line in lines:
            # Skip empty lines and lines with just whitespace
            if not line.strip():
                continue
            # Remove timestamp patterns
            line = re.sub(r'\d{2}:\d{2}:\d{2}\.\d+', 'XX:XX:XX.XXX', line)
            line = re.sub(r'\d{2}:\d{2}:\d{2}', 'XX:XX:XX', line)
            cleaned.append(line)
        return cleaned

    pre_lines = clean_output(pre_output)
    post_lines = clean_output(post_output)
    
    # Generate diff
    differ = difflib.Differ()
    diff = list(differ.compare(pre_lines, post_lines))
    
    # Process and categorize differences
    changes = {
        'added': [],
        'removed': [],
        'changed': []
    }
    
    for line in diff:
        if line.startswith('+ '):
            changes['added'].append(line[2:])
        elif line.startswith('- '):
            changes['removed'].append(line[2:])
        elif line.startswith('? '):
            continue
        else:
            changes['changed'].append(line[2:])

    # Generate the report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"{hostname}_diff_report_{timestamp}.txt"
    
    with open(report_filename, 'w') as f:
        f.write(f"Change Report for {hostname}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("Added Configurations:\n")
        f.write("-" * 40 + "\n")
        for line in changes['added']:
            f.write(f"+ {line}\n")
        f.write("\n")
        
        f.write("Removed Configurations:\n")
        f.write("-" * 40 + "\n")
        for line in changes['removed']:
            f.write(f"- {line}\n")
        f.write("\n")
        
        # Generate detailed diff using unified diff format
        f.write("Detailed Diff:\n")
        f.write("-" * 40 + "\n")
        unified_diff = difflib.unified_diff(pre_lines, post_lines, 
                                         fromfile='Pre-Check', 
                                         tofile='Post-Check',
                                         lineterm='')
        f.write('\n'.join(unified_diff))
        
    return report_filename

def config_push(hostname_list, username, password, config_commands, pre_commands, post_commands):
    results = defaultdict(dict)
    
    for hostname in hostname_list:
        hostname = hostname.strip()
        try:
            # Connect and get device type
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname, username=username, password=password, 
                         allow_agent=False, look_for_keys=False)
            
            shell = client.invoke_shell()
            time.sleep(1)
            device_type = identify_device_type(shell)
            logging.info(f"Connected to {hostname} ({device_type})")
            
            # Perform pre-checks
            logging.info(f"Performing pre-checks on {hostname}")
            results[hostname]['pre_check'] = execute_commands(shell, pre_commands, device_type)
            
            # Perform config push
            logging.info(f"Pushing configuration to {hostname}")
            results[hostname]['config'] = execute_commands(shell, config_commands, device_type)
            
            # Perform post-checks
            logging.info(f"Performing post-checks on {hostname}")
            results[hostname]['post_check'] = execute_commands(shell, post_commands, device_type)
            
            # Compare and generate diff report
            report_file = compare_outputs(results[hostname]['pre_check'],
                                       results[hostname]['post_check'],
                                       hostname)
            
            logging.info(f"Diff report generated: {report_file}")
            print(f"\nDiff report for {hostname} has been saved to: {report_file}")
            
            shell.close()
            client.close()
            
        except Exception as e:
            logging.error(f"An error occurred with {hostname}: {str(e)}")
            results[hostname]['error'] = str(e)

    return results

def main():
    hostname_list, username, password = get_user_input()
    option = input("Select an option:\n1. Config Push\n2. Pre-checks\n3. Post-checks\nEnter your choice: ").strip()
    
    if option == '1':
        config_commands, pre_commands, post_commands = get_all_commands()
        scheduled_time = get_schedule_option()

        if scheduled_time:
            now = datetime.now(pytz.timezone('US/Eastern'))
            delay = (scheduled_time - now).total_seconds()
            scheduler = sched.scheduler(time.time, time.sleep)
            scheduler.enter(delay, 1, config_push, 
                          (hostname_list, username, password, config_commands, 
                           pre_commands, post_commands))
            logging.info(f"Scheduled config push at {scheduled_time}")
            scheduler.run()
        else:
            config_push(hostname_list, username, password, config_commands, 
                       pre_commands, post_commands)
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
