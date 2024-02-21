# 
# Buy/Sell signal script
# 
# Use code  Hobbyist_Yearly_10  to save 10 percent on CMC

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

CMC_API_KEY = os.getenv('CMC_API_KEY')
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASS = os.getenv('EMAIL_PASS')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')

if not os.path.exists('data.json'):
    with open('data.json', 'w') as file:
        json.dump({}, file)

with open('data.json', 'r') as file:
    your_json_data = json.load(file)

def json_to_dataframe(your_json_data):
    try:
        return pd.DataFrame([{
                'timestamp': quote['timestamp'],
                'price': quote['quote']['USD']['price'],
                'symbol': your_json_data['data']['symbol'],
                'name': your_json_data['data']['name']
            } for quote in your_json_data['data']['quotes']
        ])
    except KeyError as e:
        print(f"Key {e} not found in JSON data")
        return pd.DataFrame()

historical_data = json_to_dataframe(your_json_data)

def fetch_data_for_intervals(symbol, intervals):
    prices_data = {}
    rsi_data = {}
    
    # Expand the 'intervals' to fetch an adequate amount of historical data for calculating RSI accurately
    max_interval_length = max(intervals.values())
    required_historical_length = timedelta(minutes=max_interval_length) + timedelta(days=14)

    # Fetch the historical data considering the longest interval for RSI calculation
    prices = fetch_historical_data(symbol, required_historical_length)

    if prices.empty:
        print("Could not fetch historical data")
        return prices_data, rsi_data

    # Calculate and save prices and RSI data for each interval
    for interval_name, interval_length in intervals.items():
        # Calculate the exact number of rows to take based on your data's time resolution
        interval_prices = prices.tail(interval_length)  # Assuming 'interval_length' can directly correspond to the number of rows
        rsi = calculate_rsi(interval_prices)
        # Adjust resampling if needed, based on the actual time resolution of your data
        prices_data[interval_name] = interval_prices
        rsi_data[interval_name] = rsi

    return prices_data, rsi_data

def fetch_historical_data(symbol, required_length):
    # Convert required_length (timedelta) to the 'start' parameter for the API call
    end_time = datetime.now(timezone.utc)
    start_time = end_time - required_length

    # Format start_time and end_time for the API request
    start = start_time.strftime('%Y-%m-%d')
    end = end_time.strftime('%Y-%m-%d')

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/historical" 
    params = {
        'symbol': symbol,
        'time_start': start.strftime('%Y-%m-%dT%H:%M:%SZ'),  # Format start time
        'time_end': end.strftime('%Y-%m-%dT%H:%M:%SZ'),  # Format end time
        'interval': interval,
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': CMC_API_KEY,  # Ensure CMC_API_KEY is defined globally or passed appropriately
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises an HTTPError if the response status code is 4XX or 5XX
        data = response.json()

        # Assuming the API returns data in a structure that includes timestamps and prices
        # You might need to adjust the following lines according to the actual structure of the data
        timestamps = [item['timestamp'] for item in data['data']]
        prices = [item['price'] for item in data['data']]

        # Convert the lists to a pandas Series for easier manipulation later
        prices_series = pd.Series(prices, index=pd.to_datetime(timestamps), name='Price')

        return prices_series
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred: {e}")  # Not all HTTP errors are due to authentication issues
    except Exception as e:
        print(f"An error occurred: {e}")

    # Return an empty Series if the fetch fails
    return pd.Series()

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

def check_buy_sell_conditions(prices, rsi):
    if rsi is None:
        return False, False  # Early exit if RSI calculation failed
    below_threshold_timeframes = {tf: (rsi[tf][-1] < 30 and prices[tf][-1] < prices[tf][-2])
                                  for tf in ['1min', '5min', '15min', '1hr']}
    above_threshold_timeframes = {tf: (rsi[tf][-1] > 70 and prices[tf][-1] > prices[tf][-2])
                                  for tf in ['1min', '5min', '15min', '1hr']}

    buy_signal = all(below_threshold_timeframes.values())
    sell_signal = all(above_threshold_timeframes.values())

    return buy_signal, sell_signal

def send_email(subject, body):
    sender_email = EMAIL_USER
    recipient = RECIPIENT_EMAIL
    sender_password = EMAIL_PASS
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

def handle_notifications(current_signal, last_signal):
    if current_signal != last_signal:
        save_state({'signal': current_signal})
        subject = f"{current_signal.capitalize()} signal for BTC"
        body = f"A {current_signal} signal has been detected for Bitcoin."
        send_email(subject, body)
        last_signal = current_signal  # Update the last_signal for the next cycle

# Assuming you have a function to load and save state; if not, here are simple implementations
def save_state(data, file_name='last_signal_state.json'):
    with open(file_name, 'w') as file:
        json.dump(data, file)

def load_state(file_name='last_signal_state.json'):
    try:
        with open(file_name, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

last_signal = load_state()

def analyze_and_notify(symbol):
    global last_signal
    
    # Defined intervals for consideration
    intervals = {
        '1min': 1,
        '5min': 5,
        '15min': 15,
        '30min': 30,
        '1hr': 60
    }
    
     # Check buy/sell conditions for each interval
    buy_signal, sell_signal = check_buy_sell_conditions(prices, rsi)

    print("last_signal: ", last_signal)
    print("current_signal: ", 'None' if not buy_signal and not sell_signal else 'buy' if buy_signal else 'sell')
    print("current_RSI: ", {tf: rsi[tf][-1] for tf in intervals})
    print("current_price: ", {tf: prices[tf][-1] for tf in intervals})

    update_state(buy_signal, sell_signal)
    
def update_state():
    global last_signal
    buy_signals = []
    sell_signals = []

    for interval_name, interval_minutes in intervals.items():
        historical_data_json = fetch_historical_data(symbol, interval_minutes)
        
        if not historical_data_json.empty:
            prices_data = historical_data_json['price']
            rsi_data = calculate_rsi(prices_data)

            current_price = prices_data.iloc[-1]
            previous_price = prices_data.iloc[-interval_minutes]

            buy_signal = rsi_data.iloc[-1] < 30 and current_price < previous_price
            sell_signal = rsi_data.iloc[-1] > 70 and current_price > previous_price
            
            buy_signals.append(buy_signal)
            sell_signals.append(sell_signal)
            
        else:
            print(f"Failed to fetch historical data for {interval_name}")
            return  # Exit if data fetching fails

    # The buy/sell signal is true if all intervals agree
    current_signal = 'buy' if all(buy_signals) else 'sell' if all(sell_signals) else 'none'
    
    # If the signal has changed, update the state and send an email
    if current_signal != last_signal.get('signal', None):
        last_signal = {'signal': current_signal}
        save_state(last_signal)
        subject = f"{symbol} {current_signal.upper()} Signal"
        body = f"A {current_signal} signal has been detected for {symbol}."
        send_email(subject, body)

def job():
    # Fetch new data every time the job runs
    historical_data_json = fetch_historical_data(symbol='BTC', required_length=timedelta(days=1))

    # Check if historical_data_json is not None or empty
    if not historical_data_json.empty:
        # Convert to DataFrame
        historical_data_df = json_to_dataframe(historical_data_json)
        
        # Perform analysis and notification
        analyze_and_notify('BTC', historical_data_df)
    else:
        # Handle the failed data retrieval
        print("Failed to fetch historical data")

    print("\nChecking...")
    analyze_and_notify('BTC')
    print("...")

schedule.every(1).minute.do(job)

print("Script started. Waiting for the next check...")
while True:
    schedule.run_pending()
    time.sleep(1)
    print(".", end="", flush=True)
