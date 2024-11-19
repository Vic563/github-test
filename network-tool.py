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
    
    # Test for Juniper devices
    shell.send('set cli screen-length 0\n')
    time.sleep(1)
    output = shell.recv(1024).decode('utf-8', errors='ignore')
    
    if 'syntax error' not in output.lower():
        # It's a Juniper device
        shell.send('show version\n')
        time.sleep(2)
        version_output = ''
        while True:
            try:
                recv_data = shell.recv(2048).decode('utf-8', errors='ignore')
                if not recv_data:
                    break
                version_output += recv_data
            except Exception:
                break
        
        # Parse the model from the show version output
        match = re.search(r'^Model:\s*(\S+)', version_output, re.MULTILINE)
        if match:
            model = match.group(1).lower()
            if 'mx' in model:
                return 'juniper-mx'
            elif 'ex' in model:
                return 'juniper-ex'
            elif 'srx' in model:
                return 'juniper-srx'
            else:
                return 'juniper-unknown'
        else:
            return 'juniper-unknown'
    
    # Test for Cisco/Arista devices
    shell.send('terminal length 0\n')
    time.sleep(1)
    output = shell.recv(1024).decode('utf-8', errors='ignore')
    
    if 'syntax error' not in output.lower():
        shell.send('show version\n')
        time.sleep(2)
        version_output = ''
        while True:
            try:
                recv_data = shell.recv(2048).decode('utf-8', errors='ignore')
                if not recv_data:
                    break
                version_output += recv_data
            except Exception:
                break
        
        if re.search(r'cisco', version_output, re.IGNORECASE):
            return 'cisco'
        elif re.search(r'arista', version_output, re.IGNORECASE):
            return 'arista'
    
    return 'unknown'

def execute_commands(shell, commands, device_type):
    """Execute commands based on device type."""
    shell.settimeout(2)
    output_data = ''
    
    # Set pagination off based on device type
    if 'juniper' in device_type:
        shell.send('set cli screen-length 0\n')
    elif device_type in ['cisco', 'arista']:
        shell.send('terminal length 0\n')
    time.sleep(1)
    shell.recv(1024)  # Clear buffer
    
    for command in commands:
        shell.send(command + '\n')
        time.sleep(1)
        while True:
            try:
                recv_data = shell.recv(1024).decode('utf-8', errors='ignore')
                if not recv_data:
                    break
                output_data += recv_data
            except Exception:
                break
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

            # Open an interactive shell
            shell = client.invoke_shell()
            time.sleep(1)

            device_type = identify_device_type(shell)
            logging.info(f"Detected device type: {device_type}")

            # Execute commands
            output = execute_commands(shell, commands, device_type)
            save_option = input(f"Do you want to save the {check_type} check output to a file? (yes/no): ").strip().lower()
            if save_option in ['yes', 'y']:
                file_path = input("Enter the file path to save the output: ").strip()
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

            # Open an interactive shell
            shell = client.invoke_shell()
            time.sleep(1)

            device_type = identify_device_type(shell)
            logging.info(f"Detected device type: {device_type}")

            # Execute commands
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
