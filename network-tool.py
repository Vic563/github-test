import getpass
import paramiko
import logging
import time

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

def execute_commands(shell, commands):
    shell.settimeout(2)
    output_data = ''
    for command in commands:
        shell.send(command + '\n')
        time.sleep(1)
        while True:
            try:
                recv_data = shell.recv(1024)
                if not recv_data:
                    break
                output_data += recv_data.decode()
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

            # Optionally, set terminal length to prevent pagination
            shell.send('terminal length 0\n')
            time.sleep(1)
            shell.recv(1000)  # Clear the buffer

            # Execute commands
            output = execute_commands(shell, commands)
            print(f"Output from {hostname}:\n{output}")

            shell.close()
            client.close()
            logging.info("Disconnected from %s", hostname)
        except Exception as e:
            logging.error("An error occurred with %s: %s", hostname, str(e))

if __name__ == "__main__":
    main()