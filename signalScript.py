# 
# Buy/Sell signal script
# 
# Use code  Hobbyist_Yearly_10  to save 10 percent on CMC
#
# 
# The script checks price data every minute.
# The script prints and emails buy/sell signal.
# The script only emails when buy or sell signal activated, do nothing if no change.
# Print should print last signal, current signal, current RSI per timeframe, and current price every minute to console.
# 
# Buy signal if a specific stock/crypto is:
# Below 35 RSI on the 5 min, 15 min, and 30 min chart.
# And if current price is below the price 5 min ago, 15 min ago, as well as 30 min ago.
# 
# Sell signal if it is:
# Above 65 RSI on the 5 min, 15 min, and 30 min chart.
# And if current price is above the price 5 min ago, 15 min ago, as well as 30 min ago.
# 

import re
import json
import os
import requests
import smtplib
import pandas as pd
import numpy as np
import schedule
import time
from datetime import timezone, datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SYMBOL='BTC'
CMC_API_KEY='API_KEY'
EMAIL_USER='email@gmail.com'
EMAIL_PASS='pass'
RECIPIENT_EMAIL='email@gmail.com'
interval='5m' # in minutes
timeframes = [5, 15, 30]

if not os.path.exists('data.json'):
    with open('data.json', 'w') as file:
        json.dump({}, file)
    print("data.json file created")
else:
    print("data.json file exists")

with open('data.json', 'r') as file:
    your_json_data = json.load(file)

# Function to load state
def load_state(file_name='last_signal_state.json'):
    try:
        with open(file_name, 'r') as file:
            data = json.load(file)
            # Ensure there's a 'signal' key in the data
            if 'signal' not in data:
                data['signal'] = 'none'  # Or any default value you see fit
            return data
    except FileNotFoundError:
        return {"signal": "none"}

# Function to save state
def save_state(data, file_name='last_signal_state.json'):
    with open(file_name, 'w') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

# Load last signal from state
last_signal = load_state()

def json_to_dataframe(data):
    try:
        quotes = data['data']['quotes']
        df = pd.DataFrame([{
                'timestamp': quote['timestamp'],
                'price': quote['quote']['USD']['price'],
                'volume_24h': quote['quote']['USD']['volume_24h'],
                'market_cap': quote['quote']['USD']['market_cap'],
                'circulating_supply': quote['quote']['USD']['circulating_supply'],
                'total_supply': quote['quote']['USD']['total_supply']
            } for quote in quotes])
        return df
    except KeyError as e:
        print(f"Key {e} not found in JSON data")
        return pd.DataFrame()

historical_data = json_to_dataframe(your_json_data)



def send_email(subject, body):
    sender_email = EMAIL_USER
    recipient = RECIPIENT_EMAIL
    sender_password = EMAIL_PASS
    print("[NOTIFICATION] Preparing to send email notification")
    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient, msg.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")


def fetch_historical_data(symbol, interval):
    match = re.match(r'^(\d+)m$', interval)
    if match:
        interval_minutes = int(match.group(1))
    else:
        print("Invalid interval format. Should be like '5m'.")
        return pd.DataFrame()  # Return an empty DataFrame in case of an invalid format

    required_data_point_count = 16
    lookback_period = interval_minutes * required_data_point_count

    # Convert required_length (timedelta) to the 'start' parameter for the API call
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_period)

    # Format start_time and end_time for the API request
    start = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    end = end_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    print(f"[FETCHING] historical data for {symbol} from {start} to {end}")

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/historical" 
    params = {
        'symbol': symbol,
        'time_start': start,  # Use the formatted start time directly
        'time_end': end,  # Use the formatted end time directly
        'interval': interval,  # Ensure 'interval' is defined. Adjust as needed based on your requirements

    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': CMC_API_KEY,  # Ensure CMC_API_KEY is defined globally or passed appropriately
    }




    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises an HTTPError if the response status code is 4XX or 5XX
        data = response.json()
        # print(data)  # Debug print to console

        prices_series = json_to_dataframe(data)  # Use the refined json_to_dataframe function

        return prices_series  # Return the DataFrame/Series with prices and timestamps
    except requests.exceptions.HTTPError as e:
        try:
            error_details = response.json()  # Ensure 'response' is defined before this line
            error_message = error_details.get('status', {}).get('error_message', 'No error message provided')
            print(f"HTTP error occurred: {e} - Error message: {error_message}")
        except ValueError:
            # If response is not in JSON format or doesn't contain the expected data
            print(f"HTTP error occurred: {e} - Unable to extract error message from response")
    except Exception as e:
        print(f"An error occurred: {e}")

    return pd.DataFrame()  # Return an empty DataFrame if the fetch fails or an error occurs




def calculate_rsi(df, period=14):
    if 'price' not in df.columns:
        raise ValueError("DataFrame does not contain a 'price' column")

    if len(df) < period:
        raise ValueError(f"Not enough data to calculate RSI, got {len(df)} points, need at least {period}")

    # Ensure the 'price' column is numeric and does not contain null values
    if df['price'].isnull().any():
        raise ValueError("Price column contains null values")
    if not np.issubdtype(df['price'].dtype, np.number):
        raise ValueError("Price column must be numeric")

    delta = df['price'].diff(1).dropna()

    # Make two series: one for gains and one for losses
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    # Calculate the exponential moving averages of gains and losses
    average_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    average_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs = average_gain / average_loss
    rsi = 100 - (100 / (1 + rs))

    rsi.index = df.index[1:]  # Align the index with the original data's index
    return rsi



# Analyze market conditions and decide signals
def analyze_market_conditions(symbol):
    global last_signal
    current_signal = "none"
    prices, rsi_values = {}, {}

    for timeframe in timeframes:
        # Correct the function call by removing the 'lookback' argument
        df = fetch_historical_data(symbol, f"{timeframe}m")  # Assuming this returns a DataFrame
        if df.empty:
            print(f"Failed to fetch data for {timeframe}m timeframe.")
            return

        if len(df) < 14:
            print(f"Not enough data to calculate RSI for {symbol}. Got {len(df)} points.")
            # Consider skipping RSI calculation or handling this case appropriately
            return

        rsi = calculate_rsi(df, period=14)
        last_price = df['price'].iloc[-1]
        first_price = df['price'].iloc[0]

        prices[timeframe] = last_price
        rsi_values[timeframe] = rsi.iloc[-1]

        buy_condition = all(rsi < 35 for rsi in rsi_values.values()) and last_price < first_price
        sell_condition = all(rsi > 65 for rsi in rsi_values.values()) and last_price > first_price

        if buy_condition:
            current_signal = "buy"
        elif sell_condition:
            current_signal = "sell"

    print(f"Last signal: {last_signal.get('signal', 'none')}, Current signal: {current_signal}, RSI: {rsi_values}, Current price: {prices[timeframes[-1]]}")

    if current_signal != last_signal.get('signal', 'none') and current_signal != "none":
        subject = f"{SYMBOL} {current_signal.upper()} Signal"
        body = f"A {current_signal} signal has been detected for {SYMBOL}."
        send_email(subject, body)
        last_signal['signal'] = current_signal  # Update last_signal with the current signal
        save_state(last_signal)  # Save the updated last_signal state

def job():
    analyze_market_conditions(SYMBOL)

schedule.every(1).minute.do(job)

print("Script started. Waiting for the next check...")
while True:
    schedule.run_pending()
    time.sleep(1)
    print(".", end="", flush=True)
