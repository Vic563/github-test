import getpass
import paramiko
import logging
import time
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_user_input():
    hostnames = input("Enter hostname(s) or IP address(es) (separated by commas): ")
    hostname_list = [h.strip() for h in hostnames.split(',')]
    username = input("Enter username: ")
    password = getpass.getpass(prompt='Enter password: ')
    return hostname_list, username, password

def get_commands():
    print("Enter commands to execute. Press Enter twice when finished:")
    commands = []
    while True:
        command = input()
        if command.lower() == 'done':
            break
        commands.append(command)
    return commands

def identify_device_type(shell):
    """Identify the network device type and model."""
    shell.settimeout(2)
    
    # Test for Juniper
    shell.send('set cli screen-length 0\n')
    time.sleep(1)
    output = shell.recv(1024).decode('utf-8')
    
    if 'syntax error' not in output.lower():
        # It's a Juniper device
        shell.send('show version\n')
        time.sleep(2)
        version_output = shell.recv(2048).decode('utf-8')
        
        # Parse Juniper model from show version
        if 'mx' in version_output.lower():
            return 'juniper-mx'
        elif 'ex' in version_output.lower():
            return 'juniper-ex'
        elif 'srx' in version_output.lower():
            return 'juniper-srx'
        return 'juniper-unknown'
    
    # Test for Cisco/Arista
    shell.send('terminal length 0\n')
    time.sleep(1)
    output = shell.recv(1024).decode('utf-8')
    
    if 'syntax error' not in output.lower():
        shell.send('show version\n')
        time.sleep(2)
        version_output = shell.recv(2048).decode('utf-8')
        
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
                recv_data = shell.recv(1024).decode('utf-8')
                if not recv_data:
                    break
                output_data += recv_data
            except Exception:
                break
    return output_data

def main():
    hostname_list, username, password = get_user_input()
    commands = get_commands()
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

if __name__ == "__main__":
    main()