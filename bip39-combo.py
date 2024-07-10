import os #DON'T FORGET TO UPDATE AND INSTALL ALL THE LIBRARIES THAT ARE NECESSARY
import requests
import time
import sys
from mnemonic import Mnemonic
from web3 import Web3
from eth_account import Account
from requests.exceptions import ConnectionError, HTTPError
from threading import Lock, Semaphore, Thread

# Enable the unaudited HD wallet features
Account.enable_unaudited_hdwallet_features()

# Constants
API_KEYS = ['API KEY 1', 'API KEY 2', 'API KEY 3']  # Replace with your Etherscan API keys
ETHERSCAN_URL = 'https://api.etherscan.io/api'
INFURA_PROJECT_ID = 'Infura Project ID'  # Replace with your Infura Project ID
w3 = Web3(Web3.HTTPProvider(f'https://mainnet.infura.io/v3/Infura Project ID'))

# Rate limiting
RATE_LIMIT = 5  # Maximum number of requests per second
semaphore = Semaphore(RATE_LIMIT)

# Global counters and lock for thread-safe updates
seed_phrase_count = 0
wallet_balance_checked = 0
wallets_with_zero_balance = 0
wallets_with_zero_tx = 0
wallets_with_tx = 0
wallets_with_balance = 0  # New statistic
lock = Lock()
start_time = time.time()

# ANSI color codes
COLOR_RESET = "\033[0m"
COLOR_VIOLET = "\033[35m"
COLOR_RED = "\033[31m"
COLOR_GREEN = "\033[32m"
COLOR_ORANGE = "\033[33m"

# Function to get balance and transaction count for an address
def get_wallet_info(address):
    global API_KEYS
    max_retries = 5
    backoff_factor = 0.3
    api_key_index = 0

    for retry in range(max_retries):
        api_key = API_KEYS[api_key_index]
        balance_url = f'{ETHERSCAN_URL}?module=account&action=balance&address={address}&tag=latest&apikey={api_key}'
        tx_count_url = f'{ETHERSCAN_URL}?module=account&action=txlist&address={address}&startblock=0&endblock=99999999&sort=asc&apikey={api_key}'

        try:
            # Acquire semaphore before making the request
            semaphore.acquire()

            balance_response = requests.get(balance_url)
            tx_count_response = requests.get(tx_count_url)

            # Release semaphore after making the request
            semaphore.release()

            balance_response.raise_for_status()
            tx_count_response.raise_for_status()

            balance_data = balance_response.json()
            tx_count_data = tx_count_response.json()

            # Check balance response
            if balance_data.get('status') != '1':
                if 'rate limit' in balance_data.get('message', '').lower():
                    api_key_index = (api_key_index + 1) % len(API_KEYS)
                    print(f"Switching to API key {api_key_index}")
                    raise ValueError("API key rate limited, switching key")
                else:
                    raise ValueError(f"Error from Etherscan: {balance_data.get('message')}")

            # Check transaction count response
            if tx_count_data.get('status') != '1':
                if 'rate limit' in tx_count_data.get('message', '').lower():
                    api_key_index = (api_key_index + 1) % len(API_KEYS)
                    print(f"Switching to API key {api_key_index}")
                    raise ValueError("API key rate limited, switching key")
                elif 'no transactions found' in tx_count_data.get('message', '').lower():
                    tx_count = 0
                else:
                    raise ValueError(f"Error from Etherscan: {tx_count_data.get('message')}")
            else:
                tx_count = len(tx_count_data['result'])

            balance = int(balance_data['result'])

            return balance, tx_count
        except (ConnectionError, HTTPError, ValueError) as e:
            print(f"Error fetching data: {e}. Retrying in {backoff_factor * (2 ** retry)} seconds...")
            time.sleep(backoff_factor * (2 ** retry))
            continue

    raise Exception("Max retries exceeded")

# Function to generate wallets from mnemonic
def generate_wallets_from_seed(seed_phrase):
    wallets = []

    for i in range(5):  # Generate the first 5 addresses
        account = Account.from_mnemonic(seed_phrase, account_path=f"m/44'/60'/0'/0/{i}")
        wallets.append(account.address)

    return wallets

# Function to generate a random seed
def generate_random_seed():
    mnemo = Mnemonic("english")
    return mnemo.generate(strength=128)

# Function to log addresses with balance to a file
def log_to_file(seed_phrase, wallet, balance):
    log_entry = f"Seed Phrase: {seed_phrase}\nWallet Address: {wallet}\nBalance: {balance} ETH\n\n"
    with open("has_balance.txt", "a") as file:
        file.write(log_entry)

# Function to log processed seed phrases
def log_processed_seed_phrases(seed_phrase):
    with open("processed_seed_phrases.txt", "a") as file:
        file.write(seed_phrase + "\n")

# Function to process a single seed phrase
def process_seed_phrase(seed_phrase):
    global seed_phrase_count, wallet_balance_checked, wallets_with_zero_balance, wallets_with_zero_tx, wallets_with_tx, wallets_with_balance

    with lock:
        seed_phrase_count += 1

    # Generate wallets
    wallets = generate_wallets_from_seed(seed_phrase)

    print(f"Seed Phrase: {seed_phrase}\n")

    # Check balances and transaction counts
    for wallet in wallets:
        try:
            balance, tx_count = get_wallet_info(wallet)
        except Exception as e:
            print(f"Failed to fetch wallet info for {wallet}: {e}")
            continue

        balance_eth = w3.from_wei(balance, 'ether')

        # Determine color for balance
        balance_color = COLOR_GREEN if balance_eth > 0 else COLOR_RED

        # Determine color for transaction count
        tx_count_color = COLOR_GREEN if tx_count > 0 else COLOR_RED

        # Print wallet address, balance, and transaction count with colors
        print(f"Wallet Address: {wallet}")
        print(f"Balance: {COLOR_RESET}{balance_eth:.6f} ETH {balance_color}")
        print(f"Transactions: {COLOR_RESET}{tx_count} {tx_count_color}")
        print()

        with lock:
            wallet_balance_checked += 1
            if balance_eth == 0:
                wallets_with_zero_balance += 1
            elif balance_eth > 0:
                wallets_with_balance += 1
            if tx_count == 0:
                wallets_with_zero_tx += 1
            elif tx_count > 0:
                wallets_with_tx += 1

        # Log to file if balance is greater than 0
        if balance_eth > 0:
            log_to_file(seed_phrase, wallet, balance_eth)

    # Log processed seed phrase
    log_processed_seed_phrases(seed_phrase)

# Function to display statistics
def display_statistics():
    global seed_phrase_count, wallet_balance_checked, wallets_with_zero_balance, wallets_with_zero_tx, wallets_with_tx, wallets_with_balance

    while True:
        time.sleep(5)  # Update statistics every second
        if os.getenv('TERM'):  # Check if TERM is set
            os.system('cls' if os.name == 'nt' else 'clear')  # Clear the terminal screen

        with lock:
            elapsed_time = time.time() - start_time
            elapsed_minutes = elapsed_time / 60
            speed = wallet_balance_checked / elapsed_time * 60 if wallet_balance_checked > 0 else 0
            print(
                f"Speed: {COLOR_ORANGE}{speed:.2f}{COLOR_RESET} W/min | "
                f"SPG: {COLOR_VIOLET}{seed_phrase_count}{COLOR_RESET} | "
                f"WBC: {COLOR_VIOLET}{wallet_balance_checked}{COLOR_RESET} | "
                f"WwB < 0: {COLOR_RED}{wallets_with_zero_balance}{COLOR_RESET} | "
                f"WwT < 0: {COLOR_RED}{wallets_with_zero_tx}{COLOR_RESET} | "
                f"WwT > 0: {COLOR_GREEN}{wallets_with_tx}{COLOR_RESET} | "
                f"WwB > 0: {COLOR_GREEN}{wallets_with_balance}{COLOR_RESET} | "
                f"Time: {elapsed_minutes:.2f} min"
            )

# Main function to run the script indefinitely
def main():
    global start_time
    start_time = time.time()
    num_threads = 1  # Process one seed phrase at a time

    # Start the statistics display thread
    stats_thread = Thread(target=display_statistics)
    stats_thread.daemon = True
    stats_thread.start()

    processed_seed_phrases = set()

    # Load already processed seed phrases
    if os.path.exists("processed_seed_phrases.txt"):
        with open("processed_seed_phrases.txt", "r") as processed_file:
            for line in processed_file:
                processed_seed_phrases.add(line.strip())

    try:
        while True:
            seed_phrase = generate_random_seed()

            # Skip processing if seed phrase is already processed
            if seed_phrase in processed_seed_phrases:
                continue

            process_seed_phrase(seed_phrase)

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Exiting gracefully...")

    except Exception as e:
        print(f"Unexpected error occurred: {e}")

    finally:
        # Save processed seed phrases to file
        with open("processed_seed_phrases.txt", "a") as file:
            for seed_phrase in processed_seed_phrases:
                file.write(seed_phrase + "\n")

        # Optional cleanup tasks
        # Ensure threads are stopped and resources released if necessary

        print("Script stopped.")

        # Exit the script cleanly
        sys.exit(0)

if __name__ == "__main__":
    main()
