from datetime import datetime
import math
import configure as config
from binance.client import Client
from processing import vwap_processing, macd_processing, rsi_processing
from data_logging import log_to_txt
from plotting import plot
from processing import local_extremas
from transactions import testTransactions


class TestStrategy:

    def __init__(self, timeframe, crypto):
        self.crypto_usdt = crypto + "usdt"
        self.timeframe = timeframe

        ###Candlesticks and ticks

        self.candlesticks = []
        self.current_tick = None
        self.prev_tick = None
        self.disableTransactions = False
        ###Stop loss variables

        self.stop_loss_flag = False
        self.stop_loss_counter = None
        self.stop_loss_counter_max = None

        ###Indicators

        ##Vwap indicator
        self.vwap_indicator = {}
        self.vwap_flag = -1
        # Assuming timeframe in minutes (To get one day)
        self.VWAP_INDICATOR_LOOKBACK = None
        self.typical_price_times_volume = []

        ##MACD
        self.EMA_MULTIPLIER_PERIODS_1 = None
        self.EMA_MULTIPLIER_PERIODS_2 = None
        self.EMA_MULTIPLIER_PERIODS_3 = None

        self.EMA_MULTIPLIER_1 = None
        self.EMA_MULTIPLIER_2 = None
        self.EMA_MULTIPLIER_3 = None

        self.ema_values_1 = {}
        self.ema_values_2 = {}
        self.macd_indicator = {}
        self.ema_values_3 = {}
        self.macd_flag = -1

        ##RSI
        self.rsi_indicator = {}
        self.last_avg_gain = None
        self.last_avg_loss = None
        self.RSI_INDICATOR_LOOKBACK = None



        ###Transactions

        ##Buy
        self.buy_orders = {}
        ##Sell
        self.sell_orders = {}
        ##Position
        self.position = {}
        ##Initial Balance
        self.balance_history = {}
        self.balance = None

        self.local_min_values = []
        self.local_max_values = []


        self.initialize_variables()
        print("Processing ...")

    def initialize_variables(self):
        # Assuming timeframe in minutes (To get one day) TODO: Make it work for hours too
        if (self.timeframe[1] == 'm'):
            self.VWAP_INDICATOR_LOOKBACK = int(1440 / int(self.timeframe[0]))
        elif (self.timeframe[1] == 'h'):
            self.VWAP_INDICATOR_LOOKBACK = int(24 / int(self.timeframe[0]))

        self.EMA_MULTIPLIER_PERIODS_1 = 12
        self.EMA_MULTIPLIER_PERIODS_2 = 26
        self.EMA_MULTIPLIER_PERIODS_3 = 9
        self.EMA_MULTIPLIER_1 = 2 / (1 + self.EMA_MULTIPLIER_PERIODS_1)
        self.EMA_MULTIPLIER_2 = 2 / (1 + self.EMA_MULTIPLIER_PERIODS_2)
        self.EMA_MULTIPLIER_3 = 2 / (1 + self.EMA_MULTIPLIER_PERIODS_3)
        self.RSI_INDICATOR_LOOKBACK = 14

        self.balance = 50
        self.stop_loss_counter = 0
        self.stop_loss_counter_max = 3

    def get_tick_from_message(self, message):
        close = message['k']['c']
        open = message['k']['o']
        high = message['k']['h']
        low = message['k']['l']
        volume = message['k']['v']

        # Just last three digit
        #time = datetime.utcfromtimestamp(math.floor(int(message['E']) / 1000))
        time = math.floor(int(message['E']) / 1000)
        open_time = math.floor(int(message['k']['t']) / 1000)
        close_time = math.floor(int(message['k']['T']) / 1000)
        #open_time = datetime.utcfromtimestamp(math.floor(int(message['k']['t']) / 1000))
        #close_time = datetime.utcfromtimestamp(math.floor(int(message['k']['T']) / 1000))
        tick = {
            "time": time,
            "open": float(open),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(volume),
            "open_time": open_time,
            "close_time": close_time
        }
        return tick

    def check_if_period_passed(self, previous_tick, current_tick):
        return previous_tick["open_time"] != current_tick["open_time"]

    ### Process tick by tick and store candlesticks
    def add_tick(self, message):
        tick = self.get_tick_from_message(message)
        ##Update previous and current tick
        if (not self.current_tick):
            self.current_tick = tick
            return
        else:
            self.prev_tick = self.current_tick
            self.current_tick = tick

        ###If new candlestick, add previous one
        if (self.check_if_period_passed(self.prev_tick, self.current_tick)):

            ###Processing after each new candlestick here:
            self.candlesticks.append(self.prev_tick)
            ##VWAP processing
            self.process_vwap()
            ##MACD
            self.process_macd()
            ##RSI
            self.process_rsi()
            ##Local minimums and maximumx
            self.local_min_values, self.local_max_values = local_extremas.local_extrema_values(self.candlesticks,order=10)

            if(not self.disableTransactions):
                #self.test_rsi_and_macd_strat()
                #self.test_macd_strat()
                #self.test_local_mins_maxs()
                #self.test_rsi_strat()
                self.test_all_strat()
            self.balance_history[self.candlesticks[-1]['open_time']] = self.balance

    ###VWAP indicator
    def process_vwap(self):
        ###Maybe make it also a dictionary ?
        self.typical_price_times_volume.append(vwap_processing.typical_price_times_volume(self.candlesticks[-1]))
        vwap = vwap_processing.process_vwap(self.candlesticks, self.typical_price_times_volume,
                                            self.VWAP_INDICATOR_LOOKBACK)
        if (vwap):
            self.vwap_indicator[self.candlesticks[-1]['open_time']] = vwap

    ###MACD and SIGNAL (Around 100 period to stabilize)
    def process_macd(self):
        closes = [candlestick['close'] for candlestick in self.candlesticks]
        ema_value_1 = macd_processing.get_ema_value(self.EMA_MULTIPLIER_PERIODS_1, self.EMA_MULTIPLIER_1,
                                                    self.ema_values_1, closes)
        ema_value_2 = macd_processing.get_ema_value(self.EMA_MULTIPLIER_PERIODS_2, self.EMA_MULTIPLIER_2,
                                                    self.ema_values_2, closes)
        macd_value = macd_processing.get_macd_value(self.ema_values_1, self.ema_values_2)
        macd_values = list(self.macd_indicator.values())
        ema_value_3 = macd_processing.get_ema_value(self.EMA_MULTIPLIER_PERIODS_3, self.EMA_MULTIPLIER_3,
                                                    self.ema_values_3, macd_values)
        if (ema_value_1):
            self.ema_values_1[self.candlesticks[-1]['open_time']] = ema_value_1
        if (ema_value_2):
            self.ema_values_2[self.candlesticks[-1]['open_time']] = ema_value_2
        if (ema_value_3):
            self.ema_values_3[self.candlesticks[-1]['open_time']] = ema_value_3
        if (macd_value):
            self.macd_indicator[self.candlesticks[-1]['open_time']] = macd_value

    ###RSI
    def process_rsi(self):

        self.last_avg_gain,self.last_avg_loss,rsi = rsi_processing.process_rsi(self.candlesticks, self.RSI_INDICATOR_LOOKBACK,self.last_avg_gain,self.last_avg_loss)
        if(rsi):
            self.rsi_indicator[self.candlesticks[-1]['open_time']] = rsi

    def log_to_txt(self, txt):
        log_to_txt.print_to_txt(
            txt_file=txt,
            candlesticks=self.candlesticks,
            vwap_indicator=self.vwap_indicator,
            macd_indicator=self.macd_indicator,
            ema_values_3=self.ema_values_3,
            buy_orders=self.buy_orders,
            sell_orders=self.sell_orders,
            balance_history=self.balance_history
        )

    def plot(self):
        return plot.plot_candlesticks(
            candlesticks=self.candlesticks,
            macd_indicator=self.macd_indicator,
            ema_values_3=self.ema_values_3,
            vwap_indicator=self.vwap_indicator,
            rsi_indicator=self.rsi_indicator,
            buy_orders=self.buy_orders,
            sell_orders=self.sell_orders,
            local_min= self.local_min_values,
            local_max= self.local_max_values)

    ##Getting previous data from Binance API, should ma
    def get_previous_data(self, old_data_time_period=10):
        client = Client(config.API_KEY, config.API_SECRET)
        if (self.timeframe[1] == "m"):
            old_time_multiplier = 60
        elif (self.timeframe[1] == "h"):
            old_time_multiplier = 3600
        unix_minus = old_data_time_period * int(self.timeframe[0]) * old_time_multiplier

        unix_time = int(datetime.utcnow().timestamp())
        old_unix_time = unix_time - unix_minus
        old_readable_time = datetime.fromtimestamp(old_unix_time).strftime("%d %b %Y %H:%M ")

        if (self.timeframe == "1m"):
            old_data_timeframe = Client.KLINE_INTERVAL_1MINUTE
        elif (self.timeframe == "5m"):
            old_data_timeframe = Client.KLINE_INTERVAL_5MINUTE
        elif (self.timeframe == "15m"):
            old_data_timeframe = Client.KLINE_INTERVAL_15MINUTE
        elif (self.timeframe == "1h"):
            old_data_timeframe = Client.KLINE_INTERVAL_1HOUR
        elif (self.timeframe == "2h"):
            old_data_timeframe = Client.KLINE_INTERVAL_2HOUR

        fetched_data = client.get_historical_klines(self.crypto_usdt.upper(), old_data_timeframe,
                                                    old_readable_time)
        old_candlesticks = []
        for row in fetched_data:
            old_candlesticks.append({
                "E": float(row[0]),
                "k": {
                    "o": row[1],
                    "h": row[2],
                    "l": row[3],
                    "c": row[4],
                    "v": row[5],
                    "T": row[6],
                    "t": row[0]
                }
            })
        # Process old data
        self.disableTransactions = True
        for old_candlestick in old_candlesticks:
            self.add_tick(old_candlestick)
        self.disableTransactions = False
    ###Transactions
    def test_macd_strat(self):
        if (self.ema_values_3 ):

            current_time = self.candlesticks[-1]['open_time']
            current_macd = self.macd_indicator[list(self.macd_indicator)[-1]]
            current_signal = self.ema_values_3[list(self.ema_values_3)[-1]]
            last_close = self.candlesticks[-1]['close']

            if (current_macd > 0):
                self.stop_loss_flag = False

            if (self.stop_loss_counter >= 3):
                print('Stop lost activated 2 times in a row')
                if (self.up_trend(number_of_candlesticks= 5)):
                    self.stop_loss_counter = 0
                return

            ###Stop loss function: If price drops below 98%
            if (self.position):
                quantity = self.position['quantity']
                position_price = self.position['position_price']
                current_quantity_price = quantity * last_close

                if (current_quantity_price < (position_price * 0.95)):
                    print("Lost one at: ",current_time)
                    self.sell_all(current_time, last_close)
                    self.stop_loss_counter += 1
                    self.stop_loss_flag = True
                    return
                if (current_quantity_price > (position_price * 1.05)):
                    if(self.up_trend()):
                        return #Do nothing
                    else:
                        self.sell_all(current_time, last_close)
                        self.stop_loss_counter = 0
                        return

            if (current_macd > current_signal):
                if (self.macd_flag == 0 and current_macd < 0 and not self.stop_loss_flag ):
                    self.buy(current_time, self.balance, last_close)
                self.macd_flag = 1
                return

            elif (current_macd < current_signal):
                if (self.macd_flag == 1 and current_macd > 0):
                    self.sell_all(current_time, last_close)
                    # Reset counter
                    self.stop_loss_counter = 0
                self.macd_flag = 0
                return


    def test_local_mins_maxs(self):



        if(len(self.candlesticks)>2):
            tf_ago = self.candlesticks[-2]['open_time']
            current_time = self.candlesticks[-1]['open_time']
            last_close = self.candlesticks[-1]['close']
            if(not self.position and self.local_min_values):
                if(self.local_min_values.get(tf_ago)):
                    self.buy(current_time, 50, last_close)
            elif(self.position and self.local_max_values):
                quantity = self.position['quantity']
                position_price = self.position['position_price']
                current_quantity_price = quantity * last_close
                if (current_quantity_price < (position_price * 0.98)):
                    print("Lost one at: ", current_time)
                    self.sell_all(current_time, last_close)
                    self.stop_loss_counter += 1
                    self.stop_loss_flag = True
                    return
                if(self.local_max_values.get(tf_ago)):
                    self.sell_all(current_time, last_close)

    def test_rsi_strat(self):
        if(self.rsi_indicator):
            current_time = self.candlesticks[-1]['open_time']
            current_rsi = self.rsi_indicator[list(self.rsi_indicator)[-1]]
            last_close = self.candlesticks[-1]['close']

            ###Stop loss function: If price drops below 98%
            if (self.position):
                quantity = self.position['quantity']
                position_price = self.position['position_price']
                current_quantity_price = quantity * last_close

                if (current_quantity_price < (position_price * 0.95)):
                    print("Lost one at: ", current_time)
                    self.sell_all(current_time, last_close)
                    return
                if (current_quantity_price > (position_price * 1.08)):
                    if (self.up_trend()):
                        return  # Do nothing
                    else:
                        self.sell_all(current_time, last_close)
                        self.stop_loss_counter = 0
                        return
            if(current_rsi<=30):
                self.buy(current_time, 50, last_close)
            elif(current_rsi>=70):
                self.sell_all(current_time, last_close)

    def test_rsi_and_macd_strat(self):
        if(self.rsi_indicator and self.ema_values_3 and self.vwap_indicator):
            current_time = self.candlesticks[-1]['open_time']
            current_rsi = self.rsi_indicator[list(self.rsi_indicator)[-1]]
            current_macd = self.macd_indicator[list(self.macd_indicator)[-1]]
            current_signal = self.ema_values_3[list(self.ema_values_3)[-1]]
            current_vwap = self.vwap_indicator[list(self.vwap_indicator)[-1]]
            last_close = self.candlesticks[-1]['close']
            if (self.position):
                quantity = self.position['quantity']
                position_price = self.position['position_price']
                current_quantity_price = quantity * last_close

                if (current_quantity_price < (position_price * 0.97)):
                    print("Lost one at: ", current_time)
                    self.sell_all(current_time, last_close)
                    return
                if (current_quantity_price > (position_price * 1.06)):
                    if (self.up_trend()):
                        return  # Do nothing
                    else:
                        self.sell_all(current_time, last_close)
                        self.stop_loss_counter = 0
                        return

            if(last_close<current_vwap):
                return

            if (current_rsi <= 30 and (current_macd/current_signal)<=3 and current_signal<0 and current_macd<0):
                self.buy(current_time, self.balance, last_close)
            elif (current_rsi >= 70 and (current_macd/current_signal)<=1.5 and current_signal>0 and current_macd>0):
                self.sell_all(current_time, last_close)

    def test_all_strat(self):
        percentage = 0.6
        number_of_candlesticks = 30
        if(len(self.vwap_indicator)>=number_of_candlesticks):
            current_time = self.candlesticks[-1]['open_time']
            last_close = self.candlesticks[-1]['close']
            current_macd = self.macd_indicator[list(self.macd_indicator)[-1]]
            current_signal = self.ema_values_3[list(self.ema_values_3)[-1]]
            if (self.position):
                quantity = self.position['quantity']
                position_price = self.position['position_price']
                current_quantity_price = quantity * last_close
                if (current_quantity_price < (position_price * 0.97)):
                    print("Lost one at: ", current_time)
                    self.sell_all(current_time, last_close)
                    return
                if (current_quantity_price > (position_price * 1.06)):
                    if (self.up_trend()):
                        return  # Do nothing
                    else:
                        self.sell_all(current_time, last_close)
                        self.stop_loss_counter = 0
                        return
            if(not self.position):
                #Not in position
                if(self.check_up_trend_vwap(number_of_candlesticks=number_of_candlesticks,percentage=percentage)):
                    #In uptrend
                    if(self.check_RSI_drop() and (current_macd/current_signal)<=1 and current_signal<0 and current_macd<0):
                        #RSI dropping and MACD and Signal converging
                        self.buy(current_time, self.balance, last_close)
            else:
                #In position
                if(self.check_RSI_up() and (current_macd/current_signal)<=1 and current_signal>0 and current_macd>0):
                    #RSI going up and MACD and Signal converging
                    self.sell_all(current_time, last_close)


        '''
        1- If uptrend: Trade, if not: Don't trade (Use VWAP to know if uptrend: Example: If 75% of last 40 candlesticks are above vwap -> Uptrend )
        2- Buy when RSI is dropping from 40 and going down AND MACD and Signal are CONVERGING (Meaning: A crossover will happen)
        3- Sell at stop loss or stop gain OR when RSI is going up from 60 AND MACD and signal are CONVERGING (Meaning: A crossover will happen)
        '''
    def check_up_trend_vwap(self,number_of_candlesticks,percentage):
        last_closes = [candlestick['close'] for candlestick in self.candlesticks[-number_of_candlesticks:]]
        last_vwaps = list(self.vwap_indicator.values())[-number_of_candlesticks:]
        counter = 0
        for i in range(len(last_closes)):
            if(last_closes[i]>last_vwaps[i]):
                counter+=1
        if((counter/number_of_candlesticks) > percentage):
            return True
        else:
            return False
    def check_RSI_drop(self):
        last_rsis = list(self.rsi_indicator.values())[-2:]
        if(last_rsis[-1]<last_rsis[-2] and last_rsis[-1]<35):
            return True
        else:
            return False
    def check_RSI_up(self):
        last_rsis = list(self.rsi_indicator.values())[-2:]
        if (last_rsis[-1] > last_rsis[-2] and last_rsis[-1] > 65):
            return True
        else:
            return False


    def up_trend(self, number_of_candlesticks = 3):
        for i in range(number_of_candlesticks, 1  ,-1):
            if(self.candlesticks[-i]['close']>self.candlesticks[-i]['open']):
                continue
            else:
                return False
        return True
    ##Buy order
    def buy(self, time, amount, price):
        # If nothing bought
        if (not self.position):
            # Append to buy orders at specific time with amount in usdt bought
            self.buy_orders[time] = amount

            ##TODO Both should be changed in live trader:
            # Set position to number of crypto bought
            self.position = {
                "time": time,
                "position_price": amount,
                "unit_price": price,
                "quantity": amount/price
            }
            # update fake balance
            self.balance = self.balance - amount

    ##Sell order
    def sell_all(self, time, price):
        # If something bought
        if (self.position):
            quantity = self.position['quantity']
            # Append to sell orders at specific time with amount in usdt sold (current price * amount of crypto from last position)
            self.sell_orders[time] = price * quantity

            ##TODO Both should be changed in live trader:
            # Empty position after selling
            self.position.clear()
            # update fake balance
            self.balance = self.balance + price * quantity

    def sell(self, time, amount, price):
        pass
