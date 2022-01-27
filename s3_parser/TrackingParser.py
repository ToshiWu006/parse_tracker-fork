from basic import datetime_to_str, timing, logging_channels, datetime_range, filterListofDictByDict, to_datetime
from definitions import ROOT_DIR
from db import MySqlHelper
import datetime, os, pickle, json
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
import matplotlib.pyplot as plt

class TrackingParser:
    def __init__(self, web_id, date_utc8_start='2022-01-01', date_utc8_end='2022-01-11', use_db=True):
        self.web_id = web_id
        self.use_db = use_db
        self.event_type_list = ['load', 'leave', 'timeout', 'addCart', 'removeCart', 'purchase']
        self.dict_object_key = {'addCart':'cart', 'removeCart':'remove_cart', 'purchase':'purchase'}
        self.dict_settings = self.fetch_parse_key_settings(web_id)
        if use_db:
            self.data_list = self.fetch_six_events_data_by_daterange(web_id, date_utc8_start, date_utc8_end)
        else: ## use local storage
            self.data_list = self.get_data_by_daterange(date_utc8_start, date_utc8_end)
        # self.data_list_filter = filterListofDictByDict(self.data_list, dict_criteria={"web_id": web_id})  # "web_id":"nineyi11"
        self.df_loaded = self.get_df('load')
        self.df_leaved = self.get_df('leave')
        self.df_timeout = self.get_df('timeout')
        self.df_addCart = self.get_df('addCart')
        self.df_removeCart = self.get_df('removeCart')
        self.df_purchased = self.get_df('purchase')
        # self.uuid_load = list(set(self.df_loaded['uuid']))
        # self.uuid_purchased = list(set(self.df_purchased['uuid']))
        self.features = ['pageviews', 'time_pageview_total', 'click_count_total', 'landing_count', 'max_pageviews', 'device']

    def __str__(self):
        return "TrackingParser"

    ## load, leave, timeout, addCart, removeCart, purchase
    @staticmethod
    @logging_channels(['clare_test'])
    def save_raw_event_table(data_list, date, hour):
        event_type_list = ['load', 'leave', 'timeout', 'addCart', 'removeCart', 'purchase']
        df_list = []
        for event_type in event_type_list:
            df = TrackingParser.build_raw_event_df(data_list, event_type, date, hour)
            ## drop duplicate using unique key in table
            df.drop_duplicates(subset=['web_id','event_type','timestamp','uuid'], inplace=True)
            # if event_type == 'addCart' or :


            if event_type=='load': ## bigger than others
                query = MySqlHelper.generate_update_SQLquery(df, 'tracker.raw_event_load', SQL_ACTION="INSERT INTO")
            elif event_type=='leave': ## 2nd large
                query = MySqlHelper.generate_update_SQLquery(df, 'tracker.raw_event_leave', SQL_ACTION="INSERT INTO")
            elif event_type=='purchase': ## more important
                query = MySqlHelper.generate_update_SQLquery(df, 'tracker.raw_event_purchase', SQL_ACTION="INSERT INTO")
            else: ## addCart, removeCart, timeout
                query = MySqlHelper.generate_update_SQLquery(df, 'tracker.raw_event', SQL_ACTION="INSERT INTO")
            MySqlHelper('tracker').ExecuteUpdate(query, df.to_dict('records'))
            print(f'finish saving {event_type} into db at {date} {hour}:00:00')
            df_list += [df]
        return df_list

    @staticmethod
    def build_raw_event_df(data_list, event_type, date, hour):
        object_key = {'addCart':'cart', 'removeCart':'remove_cart', 'purchase':'purchase', 'load':'load'}
        data_list_filter = filterListofDictByDict(data_list, dict_criteria={"event_type":event_type})

        df = pd.DataFrame(data_list_filter)
        df['date'], df['hour'] = [date]*df.shape[0], [hour]*df.shape[0]
        if event_type in object_key.keys():
            df.rename(columns={object_key[event_type]: 'event_value'}, inplace=True)
            df['event_key'] = [event_type] * df.shape[0]
        if 'behavior_type' in df.columns:
            df.drop(columns=['behavior_type'], inplace=True)
        df.dropna(inplace=True)
        # df['event_key'] = [event_type] * df.shape[0]
        # df['event_value'] = [json.dumps(row) for row in df['event_value']]
        # df['event_key'] = [event_type] * df.shape[0]
        if event_type=='load':
            df['event_value'] = [json.dumps(row) for row in df['event_value']]
        elif event_type=='leave' or event_type=='timeout':
            df['event_value'] = ['_'] * df.shape[0]
            if 'record_user' in df.columns:
                df['record_user'] = [json.dumps(row) for row in df['record_user']]
            else:
                df['record_user'] = ['_'] * df.shape[0]
        else: ## addCart, removeCart, purchase
            df['event_value'] = [json.dumps(row) for row in df['event_value']]
            if 'record_user' in df.columns:
                df['record_user'] = [json.dumps(row) for row in df['record_user']]
            else:
                df['record_user'] = ['_'] * df.shape[0]
            # df['record_user'] = [json.dumps(row) for row in df['record_user']]

        criteria_len = {'web_id': 45, 'uuid': 36, 'ga_id': 45, 'fb_id': 45, 'timestamp': 16,
                        'event_type': 16}
        df = TrackingParser.clean_before_sql(df, criteria_len)
        return df


    @staticmethod
    def clean_before_sql(df, criteria_len={'web_id': 45, 'uuid': 36, 'ga_id': 45, 'fb_id': 45, 'timestamp': 16,
                                           'event_type': 16}):
        """

        Parameters
        ----------
        df: DataFrame to enter sql table
        criteria_len: convert to str and map(len) <= criteria

        Returns
        -------

        """
        cols = criteria_len.keys()
        for col in cols:
            if col in df.columns:
                df[col] = df[col].astype(str)
                df = df[df[col].map(len) <= criteria_len[col]]
        return df

    @logging_channels(['clare_test'])
    def get_df(self, event_type):
        data_list_filter = filterListofDictByDict(self.data_list, dict_criteria={"web_id": self.web_id, "event_type":event_type})
        dict_list = []
        if event_type=='load':
            for data_dict in data_list_filter:
                dict_list += self.fully_parse_loaded(data_dict, self.use_db)
        elif event_type=='leave' or event_type=='timeout':
            for data_dict in data_list_filter:
                dict_list += self.fully_parse_leaved_timeout(data_dict)
        ## addCart, removeCart, purchase
        else:
            for data_dict in data_list_filter:
                dict_list += self.fully_parse_object(data_dict, event_type, self.use_db)
        df = pd.DataFrame(dict_list)
        return df

    ## addCart,removeCart,purchased events
    def fully_parse_object(self, data_dict, event_type, use_db):
        object_key = self.dict_object_key[event_type]
        key_join_list, key_rename_list = self.dict_settings[event_type]
        universial_dict = self.parse_rename_universial(data_dict)
        record_dict = self.parse_rename_record_user(data_dict)
        object_dict_list = self.parse_rename_object(data_dict, key_join_list, key_rename_list, object_key, use_db)
        result_dict_list = []
        for object_dict in object_dict_list:
            object_dict.update(universial_dict)
            object_dict.update(record_dict)
            result_dict_list += [object_dict]
        return result_dict_list

    ## loaded event
    @staticmethod
    def fully_parse_loaded(data_dict, use_db):
        universial_dict = TrackingParser.parse_rename_universial(data_dict)
        key_list = ['dv', 'ul', 'un', 'm_t', 'i_l', 'ps', 't_p_t', 's_id', 's_idl', 'l_c',
                    'c_c_t', 'mt_nm', 'mt_ns', 'mt_nc', 'mt_nd', 'mps', 'mt_p', 'mt_p_t', 'ms_d']
        key_rename_list = ['device', 'url_last', 'url_now', 'meta_title', 'is_landing',
                           'pageviews', 'time_pageview_total', 'session_id', 'session_id_last', 'landing_count',
                           'click_count_total', 'max_time_no_move', 'max_time_no_scroll', 'max_time_no_click', 'max_time_no_scroll_depth',
                           'max_pageviews', 'max_time_pageview', 'max_time_pageview_total', 'max_scroll_depth']
        if use_db:
            object_dict = json.loads(data_dict['event_value'])
        else:
            object_dict = data_dict['load']
        loaded_dict = {}
        for key, key_rename in zip(key_list, key_rename_list):
            if key not in object_dict.keys():
                loaded_dict.update({key_rename: -1})
            else:
                loaded_dict.update({key_rename: object_dict[key]})
        universial_dict.update(loaded_dict)
        return [universial_dict]

    ## leaved and timeout event
    @staticmethod
    def fully_parse_leaved_timeout(data_dict):
        universial_dict = TrackingParser.parse_rename_universial(data_dict)
        record_dict = TrackingParser.parse_rename_record_user(data_dict)
        universial_dict.update(record_dict)
        return [universial_dict]

    @staticmethod
    def parse_rename_universial(data_dict):
        key_list = ['web_id', 'uuid', 'ga_id', 'fb_id', 'timestamp']
        universial_dict = {}
        for key in key_list:
            if key in data_dict.keys():
                universial_dict.update({key: data_dict[key]})
            else:
                universial_dict.update({key: '_'})
        return universial_dict

    @staticmethod
    def parse_rename_record_user(data_dict):
        record_user_dict = data_dict['record_user']
        if type(record_user_dict)==str:
            record_user_dict = json.loads(record_user_dict)
        key_list = ['dv', 'ul', 'un', 'm_t', 's_h',
                    'w_ih', 't_p', 's_d', 's_d_', 'c_c',
                    'c_c_t', 't_nm', 't_ns', 't_nc', 'mt_nm',
                    'mt_ns', 'mt_nsa', 'mt_nda', 'mt_nd', 'mt_nd_',
                    'mt_nc', 'i_l', 's_idl', 's_id', 'ps',
                    't_p_t', 't_p_tl', 'mps', 'mt_p', 'mt_p_t',
                    'ms_d', 'ms_d_p', 'ms_d_pl', 'mt_nml', 'mt_nsl',
                    'mt_ncl', 'ms_dl', 'l_c']
        key_rename_list = ['device', 'url_last', 'url_now', 'meta_title', 'scroll_height',
                           'window_innerHeight', 'time_pageview', 'scroll_depth', 'scroll_depth_px', 'click_count',
                           'click_count_total', 'time_no_move', 'time_no_scroll', 'time_no_click', 'max_time_no_move',
                           'max_time_no_scroll', 'max_time_no_scroll_array', 'max_time_no_scroll_depth_array',
                           'max_time_no_scroll_depth', 'max_time_no_scroll_depth_px',
                           'max_time_no_click', 'is_landing', 'session_id_last', 'session_id', 'pageviews',
                           'time_pageview_total', 'time_pageview_total_last', 'max_pageviews', 'max_time_pageview',
                           'max_time_pageview_total',
                           'max_scroll_depth', 'max_scroll_depth_page', 'max_scroll_depth_page_last',
                           'max_time_no_move_last', 'max_time_no_scroll_last',
                           'max_time_no_click_last', 'max_scroll_depth_last', 'landing_count']
        record_dict = {}
        for key, key_rename in zip(key_list, key_rename_list):
            if key in record_user_dict.keys():
                record_dict.update({key_rename: record_user_dict[key]})
            else:
                record_dict.update({key_rename: -1})
        return record_dict


    ## main for parse and rename 'addcart', 'removeCart', 'purchase' event
    @staticmethod
    def parse_rename_object(data_dict, key_join_list, key_rename_list, object_key='purchase', use_db=True):
        if use_db:
            collection_dict, dict_object = {}, json.loads(json.loads(data_dict['event_value']))
        else:
            collection_dict, dict_object = {}, json.loads(data_dict[object_key])
        value_list = []
        n_list = 0
        ## parse dict type key and store list type key
        for key, key_rename in zip(key_join_list, key_rename_list):
            key_list = key.split('.')
            value = ''
            if len(key_list) == 1:  ##directly access dict
                for k in key_list:
                    collection_dict.update({key_rename: dict_object[k]})
            else:  ## parse multiple layer
                for key in key_list:
                    if value == '':  ## 1st level
                        value = '_' if key == 'empty' else dict_object[key]
                    elif type(value) == dict:  ## 2nd, 3rd... level
                        value = '_' if key == 'empty' else value[key]
                        collection_dict.update({key_rename: value})
                    elif type(value) == list:  ## 2nd, 3rd... level(parse list)
                        n_list = len(value)
                        for v in value:
                            if key in v.keys():
                                value = '_' if key == 'empty' else v[key]
                            else:
                                value = '_'
                            value_list += [value]
                    else:
                        print('do nothing')
        ## for parse multiple objects in a main_object
        if value_list == []:
            collection_purchase_dict_list = [collection_dict]
        else:
            # create multiple purchase record
            n_dict_key = len(collection_dict.keys())
            n_dict_list_key = int(len(value_list) / n_list)
            collection_purchase_dict_list = []
            if n_list != 0:
                for i in range(n_list):
                    temp_dict = {}
                    for j in range(n_dict_list_key):
                        temp_dict.update({key_rename_list[n_dict_key + j]: value_list[n_list * j + i]})
                    temp_dict.update(collection_dict)
                    collection_purchase_dict_list += [temp_dict]
            else:
                collection_purchase_dict_list = [collection_dict]
        return collection_purchase_dict_list


    @staticmethod
    @timing
    def fetch_parse_key_settings(web_id):
        query = f"""SELECT parsed_purchase_key, parsed_purchase_key_rename, parsed_addCart_key, parsed_addCart_key_rename,
                            parsed_removeCart_key, parsed_removeCart_key_rename
                            FROM cdp_tracking_settings where web_id='{web_id}'"""
        print(query)
        data = MySqlHelper("rheacache-db0").ExecuteSelect(query)
        settings = [x.split(',') for x in data[0]]
        dict_settings = {}
        for i,event_type in enumerate(['purchase', 'addCart', 'removeCart']):
            dict_settings.update({event_type: settings[i*2:(i+1)*2]})
        return dict_settings

    ################################# get data using sql #################################
    @staticmethod
    def generate_sql_query_raw_event(web_id, table='raw_event', date_utc8_start='2022-01-01', date_utc8_end='2022-01-11'):
        columns = ['uuid', 'timestamp', 'event_type', 'coupon', 'record_user', 'event_key', 'event_value', 'date', 'hour']
        query = f"""
        SELECT 
            {','.join(columns)}
        FROM
            {table}
        WHERE
            web_id = '{web_id}' AND 
            date BETWEEN '{date_utc8_start}' AND '{date_utc8_end}'
        """
        return query, columns

    @staticmethod
    @timing
    def fetch_six_events_data_by_daterange(web_id, date_utc8_start='2022-01-01', date_utc8_end='2022-01-11'):
        table_list = ['raw_event_load', 'raw_event_purchase', 'raw_event']
        data_list = []
        for table in table_list:
            query, columns = TrackingParser.generate_sql_query_raw_event(web_id, table, date_utc8_start, date_utc8_end)
            data_list += MySqlHelper("tracker").ExecuteSelect(query)
        df = pd.DataFrame(data_list, columns=columns)
        df['web_id'] = [web_id]*df.shape[0]
        return df.to_dict('records')

    ################################# get data using local storage #################################
    @staticmethod
    def get_file_byDatetime(datetime_utc0):
        """

        Parameters
        ----------
        datetime_utc0: with format, str:'2022-01-01 10:00:00' or datetime.datetime: 2022-01-01 10:00:00

        Returns: data_list
        -------

        """
        ## convert to datetime.datetime
        if type(datetime_utc0)==str:
            datetime_utc0 = datetime.datetime.strptime(datetime_utc0, "%Y-%m-%d %H:%M:%S")
        MID_DIR = datetime.datetime.strftime(datetime_utc0, format="%Y/%m/%d/%H")
        path = os.path.join(ROOT_DIR, "s3data", MID_DIR, "rawData.pickle")
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                data_list = pickle.load(f)
        return data_list

    @staticmethod
    def get_file_byHour(date_utc0, hour_utc0='00'):
        """

        Parameters
        ----------
        date_utc0: with format, str:'2022-01-01' or str:'2022/01/01'
        hour_utc0: with format, str:'00'-'23' or int:0-23

        Returns: data_list
        -------

        """
        if type(date_utc0)==datetime.datetime:
            date_utc0 = datetime.datetime.strftime(date_utc0, '%Y-%m-%d')
        if type(hour_utc0)==int:
            hour_utc0 = f"{hour_utc0:02}"
        path = os.path.join(ROOT_DIR, "s3data", date_utc0.replace('-', '/'), hour_utc0, "rawData.pickle")
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                data_list = pickle.load(f)
        return data_list

    @staticmethod
    def get_data_by_daterange(date_utc8_start='2022-01-01', date_utc8_end='2022-01-11'):
        num_days = (to_datetime(date_utc8_end) - to_datetime(date_utc8_start)).days+1
        date_utc8_list = [to_datetime(date_utc8_start) + datetime.timedelta(days=x) for x in range(num_days)]
        data_list = []
        for date_utc8 in date_utc8_list:
            data_list += TrackingParser.get_data_by_date(date_utc8)
        return data_list

    @staticmethod
    def get_data_by_date(date_utc8):
        file_list = TrackingParser.get_a_day_file_list(date_utc8)
        data_list = []
        for file in file_list:
            if os.path.isfile(file):
                with open(file, 'rb') as f:
                    data_list += pickle.load(f)
        return data_list

    @staticmethod
    def get_a_day_file_list(date_utc8):
        if type(date_utc8) == datetime.datetime:
            datetime_utc0 = date_utc8 + datetime.timedelta(hours=-8)
        else:
            datetime_utc0 = datetime.datetime.strptime(date_utc8, "%Y-%m-%d") + datetime.timedelta(hours=-8)
        datetime_list = [datetime_utc0 + datetime.timedelta(hours=x) for x in range(24)]
        file_list = [
            os.path.join(ROOT_DIR, "s3data", datetime_to_str(root_folder, pattern="%Y/%m/%d/%H"), "rawData.pickle") for
            root_folder in datetime_list]
        return file_list
################################# get data using local storage #################################



@timing
def fetch_91app_web_id():
    query = f"""SELECT web_id
                        FROM cdp_tracking_settings where platform='91'"""
    print(query)
    data = MySqlHelper("rheacache-db0").ExecuteSelect(query)
    web_id_list = [d[0] for d in data]
    return web_id_list


def collect_from_web_id_list(web_id_list, date_utc8_start, date_utc8_end):
    df_loaded_all = pd.DataFrame()
    df_purchased_all = pd.DataFrame()
    len_loaded = {}
    for i,web_id in enumerate(web_id_list):
        tracking = TrackingParser(web_id, date_utc8_start, date_utc8_end)

        df_loaded = tracking.df_loaded
        l = df_loaded.shape[0]
        len_loaded.update({web_id:l})
        if l==0:
            continue
        df_loaded['uuid'] = df_loaded.sort_values(by=['timestamp'])['uuid'].astype(str)
        df_loaded = df_loaded[df_loaded['uuid'].map(len)==36]
        df_purchased = tracking.df_purchased
        if i==0:
            df_loaded_all = df_loaded
            df_purchased_all = df_purchased
        else:
            df_loaded_all = df_loaded_all.append(df_loaded)
            df_purchased_all = df_purchased_all.append(df_purchased)
    return df_loaded_all, df_purchased_all, len_loaded


def collect_features(df_loaded, df_purchased, keys_collect=['uuid', 'pageviews', 'time_pageview_total']):
    uuid_load = list(set(df_loaded['uuid']))
    uuid_purchased = list(set(df_purchased['uuid']))
    dict_collect_list = []
    # keys_collect = ['uuid', 'device', 'pageviews', 'time_pageview_total', 'landing_count',
    #                 'click_count_total', 'max_pageviews', 'max_time_pageview', 'max_time_pageview_total', 'max_scroll_depth']
    # keys_collect = ['uuid', 'pageviews', 'time_pageview_total']
    for i,uuid in enumerate(uuid_load):
        dict_collect = {}
        df_query = df_loaded.query(f"uuid=='{uuid}'").iloc[-1]
        for key in keys_collect:
            vlaue = df_query[key]
            dict_collect.update({key: vlaue})
            if key=='uuid':
                if vlaue in uuid_purchased:
                    dict_append = {'is_purchased': 1}
                else:
                    dict_append = {'is_purchased': 0}
                dict_collect.update(dict_append)

        dict_collect_list += [dict_collect]
        if i%100==0:
            print(f"finish {i}")
    df_collect = pd.DataFrame(dict_collect_list)
    return df_collect

def binning2(data, binwidth, start=None, end=None, xlabel='value', ylabel='probability density', show=True, density=True):
    if start==None:
        start = min(data)
    if end == None:
        end = max(data)
    bin_edge = np.arange(start, end+1, binwidth)
    center = np.arange(start+binwidth/2, end-binwidth/2+1, binwidth)
    fig, ax = plt.subplots(figsize=(10, 8))
    pd, edges, patches = plt.hist(data, bins=bin_edge, density=density)
    ax.bar(center, pd, width=binwidth, color="silver", edgecolor="white")
    ax.set_xlabel(f'{xlabel}', fontsize=22)
    ax.set_ylabel(f'{ylabel}', fontsize=22)
    if show==False:
        plt.close(fig)
    return pd, center, fig, ax

def visualization_feature(df_collect, feature='pageviews', binwidth=1, bin_start=0, bin_end=50, y_low=None, y_high=None):
    feature_values_purchased = np.array(df_collect[df_collect['is_purchased']==1][feature]).astype('int')
    pd1, center1, fig, ax = binning2(feature_values_purchased, binwidth=binwidth, start=bin_start, end=bin_end, show=False)

    feature_values_not_purchased = np.array(df_collect[df_collect['is_purchased']==0][feature]).astype('int')
    pd0, center0, fig, ax = binning2(feature_values_not_purchased, binwidth=binwidth, start=bin_start, end=bin_end, show=False)

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.bar(center0, pd0, width=binwidth, color="blue", edgecolor="white", alpha=0.5)
    ax.bar(center1, pd1, width=binwidth, color="red", edgecolor="white", alpha=0.5)
    ax.set_xlabel(f'{feature}', fontsize=22)
    ax.set_ylabel(f'probability density', fontsize=22)
    plt.xlim([bin_start, bin_end])
    if y_low!=None and y_high!=None:
        plt.ylim([y_low, y_high])
    plt.show()


### normalize to mean = 0, std = 1
def normalize_data(data):
    data = np.array(data)
    data_nor = []
    for datum in data.T:
        mean = np.mean(datum)
        std = np.std(datum, ddof=1)
        datum_nor = (datum-mean)/std
        data_nor += [datum_nor]
    return np.nan_to_num(np.array(data_nor).T)


def append_purchased_column(df, uuid_purchased):
    df_collect = df.copy()
    is_purchased_list = [1 if row['uuid'] in uuid_purchased else 0 for i,row in df_collect.iterrows()]
    df_collect['is_purchased'] = is_purchased_list
    return df_collect



if __name__ == "__main__":
    web_id = "nineyi1105"
    date_utc8_start = "2022-01-19"
    date_utc8_end = "2022-01-19"
    tracking = TrackingParser(web_id, date_utc8_start, date_utc8_end)
    df_loaded = tracking.df_loaded
    df_purchased = tracking.df_purchased

    # web_id = "94monster"
    # df = TrackingParser.fetch_six_events_data_by_daterange(web_id, date_utc8_start='2022-01-18', date_utc8_end='2022-01-18')

    # uuid_load = list(set(df_loaded['uuid']))
    # uuid_purchased = list(set(df_purchased['uuid']))
    # session_purchased = {row['uuid']:[row['session_id_last'],row['session_id']] for i,row in df_purchased.iterrows()}
    # dict_collect_list = []
    # keys_collect = ['uuid', 'device', 'pageviews', 'time_pageview_total', 'landing_count',
    #                 'click_count_total', 'max_pageviews', 'max_time_pageview', 'max_time_pageview_total', 'max_scroll_depth']
    #
    # df_loaded_purchased = df_loaded.query(f"uuid in {uuid_purchased}").sort_values(by=['uuid', 'timestamp'])
    # # keys_collect = ['uuid', 'max_pageviews', 'max_time_pageview_total', 'click_count_total']
    # # for i,uuid in enumerate(uuid_load):
    # #     dict_collect = {}
    # #     df_query = df_loaded.query(f"uuid=='{uuid}'").iloc[-1]
    # #     for key in keys_collect:
    # #         vlaue = df_query[key]
    # #         dict_collect.update({key: vlaue})
    # #         if key=='uuid':
    # #             if vlaue in uuid_purchased:
    # #                 dict_append = {'is_purchased': 1}
    # #             else:
    # #                 dict_append = {'is_purchased': 0}
    # #             dict_collect.update(dict_append)
    # #
    # #     dict_collect_list += [dict_collect]
    # #     if i%100==0:
    # #         print(f"finish {i}")
    # # df_collect = pd.DataFrame(dict_collect_list)
    # df_collect = append_purchased_column(df_loaded, uuid_purchased)[keys_collect+['is_purchased']]
    #
    #
    # from sklearn.decomposition import PCA
    # # data_purchased = normalize_data(np.array(df_collect.query(f"is_purchased==1"))[:,2:])
    # data_purchased = np.array(df_collect.query(f"is_purchased==1"))[:,2:]
    #
    # pca = PCA(n_components=2)
    # result = pca.fit(data_purchased)
    # transform_purchased = result.transform(data_purchased)
    #
    # # data_not_purchased = normalize_data(np.array(df_collect.query(f"is_purchased==0"))[:,2:])
    # data_not_purchased = np.array(df_collect.query(f"is_purchased==0"))[:,2:]
    #
    # pca = PCA(n_components=2)
    # result = pca.fit(data_not_purchased)
    # transform_not_purchased = result.transform(data_not_purchased)
    # plt.figure()
    # plt.plot(transform_not_purchased[:,0], transform_not_purchased[:,1], 'bo')
    # plt.plot(transform_purchased[:,0], transform_purchased[:,1], 'ro')
    # plt.show()
    #
    #
    #
    # data = normalize_data(np.array(df_collect)[:,6:])
    # label = np.array(df_collect)[:,1]
    # pca = PCA(n_components=2)
    # result = pca.fit(data)
    # transform_data = result.transform(data)
    #
    # plt.figure()
    # plt.plot(transform_data[label==0,0], transform_data[label==0,1], 'bo')
    # plt.plot(transform_data[label==1,0], transform_data[label==1,1], 'r*')
    # plt.show()
    #
    #
    # ## clustering
    # from sklearn.mixture import GaussianMixture
    # data = np.array(df_collect)[:,6:]
    # data_nor = normalize_data(data)
    # label = np.array(df_collect)[:,1]
    # pca = PCA(n_components=2)
    # result = pca.fit(data_nor)
    # transform_data = result.transform(data_nor)
    #
    # gmm = GaussianMixture(n_components=2, tol=1e-5, init_params='random')
    # # model = Birch(threshold=0.05, n_clusters=5)
    # ##  fit the model
    # gmm.fit(transform_data)
    # ## assign a cluster to each example
    # label = gmm.predict(transform_data)
    # plt.figure()
    # data_passive, data_active = [], []
    # for i, (row,l) in enumerate(zip(transform_data,label)):
    #     if row[1]>0 and row[0]>0: ## class 1
    #         plt.plot(row[0], row[1], 'r*')
    #         data_passive += [data[i]]
    #     else:
    #         plt.plot(row[0], row[1], 'bo')
    #         data_active += [data[i]]
    # plt.show()
    # data_passive, data_active = np.array(data_passive).astype(int), np.array(data_active).astype(int)
    #
    # plt.figure()
    # for i, (row,l) in enumerate(zip(transform_data,label)):
    #     if l==1: ## class 1
    #         plt.plot(row[0], row[1], 'r*')
    #     else:
    #         plt.plot(row[0], row[1], 'bo')
    # plt.show()




    #
    #
    # web_id_list = fetch_91app_web_id()
    # # web_id_list = ['nineyi1105', 'nineyi11185', 'nineyi123', 'nineyi14267', 'nineyi1849']
    # date_utc8_start = "2022-01-19"
    # date_utc8_end = "2022-01-19"
    # df_loaded_all, df_purchased_all, len_loaded = collect_from_web_id_list(web_id_list, date_utc8_start, date_utc8_end)
    # keys_collect = ['uuid', 'device', 'pageviews', 'time_pageview_total', 'landing_count', 'click_count_total',
    #                 'max_pageviews', 'max_time_pageview', 'max_time_pageview_total', 'max_scroll_depth']
    # df_collect = collect_features(df_loaded_all, df_purchased_all, keys_collect=keys_collect)
    # df_collect['mean_max_time_per_page'] = df_collect['max_time_pageview_total']/df_collect['max_pageviews']
    # keys_select = ['max_pageviews', 'landing_count', 'click_count_total', 'max_time_pageview_total', 'max_scroll_depth']
    # X = np.array(df_collect[keys_select]).astype('int')
    # y = np.array(df_collect['is_purchased']).astype('int')
    #
    # model = LogisticRegression(random_state=0).fit(X, y)
    # prob = model.predict_proba(X)
    # predict = model.predict(X)
    # df_collect_predict = df_collect.copy()
    # df_collect_predict['prob'] = prob[:,1]
    # df_collect_predict['predict'] = predict
    #
    # model.score(X, y)
    # visualization_feature(df_collect, feature='device', binwidth=1, bin_start=0, bin_end=5, y_low=0, y_high=0.5)
    # visualization_feature(df_collect, feature='pageviews', binwidth=1, bin_start=0, bin_end=50, y_low=0, y_high=0.2)
    # visualization_feature(df_collect, feature='time_pageview_total', binwidth=50, bin_start=0, bin_end=1000, y_low=0, y_high=0.01)
    # visualization_feature(df_collect, feature='landing_count', binwidth=1, bin_start=0, bin_end=30, y_low=0, y_high=0.6)
    # visualization_feature(df_collect, feature='click_count_total', binwidth=2, bin_start=0, bin_end=150, y_low=0, y_high=0.1)
    # visualization_feature(df_collect, feature='max_pageviews', binwidth=1, bin_start=0, bin_end=50, y_low=0, y_high=0.2)
    # visualization_feature(df_collect, feature='max_time_pageview', binwidth=50, bin_start=0, bin_end=2000, y_low=0, y_high=0.015)
    # visualization_feature(df_collect, feature='max_time_pageview_total', binwidth=100, bin_start=0, bin_end=5000, y_low=0, y_high=0.008)
    # visualization_feature(df_collect, feature='max_scroll_depth', binwidth=1, bin_start=0, bin_end=100, y_low=0, y_high=0.8)
    #
    # visualization_feature(df_collect, feature='mean_max_time_per_page', binwidth=5, bin_start=0, bin_end=200, y_low=0, y_high=0.1)
    #
    # from sklearn.svm import SVC
    # from sklearn.pipeline import make_pipeline
    # from sklearn.preprocessing import StandardScaler
    # svm = make_pipeline(StandardScaler(), SVC(gamma='scale', kernel='rbf'))
    #
    # # svm = SVC()
    # svm.fit(X, y)
    # predictions_svm = svm.predict(X)
    # df_collect_predict['predict_svm'] = predictions_svm
    #
    # from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
    # from sklearn.model_selection import train_test_split
    #
    # X_train, X_test, y_train, y_test = train_test_split(X, y, test_size = 0.2, random_state = 2)
    # RFC = RandomForestClassifier(n_estimators=100, criterion='gini')
    # RFC.fit(X_train, y_train)
    # predictions_rf = RFC.predict(X_test)
    #
    # result = np.empty((len(y_test), 2))
    # result[:,0], result[:,1] = y_test, RFC.predict(X_test)
    # result_train = np.empty((len(y_train), 2))
    # result_train[:,0], result_train[:,1] = y_train, RFC.predict(X_train)
    #
    # df_collect_predict['predict_rf'] = RFC.predict(X)
    # RFC.feature_importances_






    # df_binning = df_collect[df_collect['is_purchased']==1]
    # pageviews = np.array(df_binning)[:,2].astype('int')
    # pd1, center1, fig, ax = binning2(pageviews, binwidth=1, start=0, end=50, xlabel='pageviews', ylabel='probability density')
    #
    # df_binning = df_collect[df_collect['is_purchased']==0]
    # pageviews = np.array(df_binning)[:,2].astype('int')
    # pd0, center0, fig, ax = binning2(pageviews, binwidth=1, start=0, end=50, xlabel='pageviews', ylabel='probability density')
    #
    # fig, ax = plt.subplots(figsize=(10, 8))
    # ax.bar(center0, pd0, width=1, color="silver", edgecolor="white")
    # ax.bar(center1, pd1, width=1, color="red", edgecolor="white", alpha=0.5)
    # ax.set_xlabel(f'pageviews', fontsize=22)
    # ax.set_ylabel(f'probability density', fontsize=22)
    # # plt.xlim([0, 50])
    # plt.show()


    # web_id = "nineyi123"
    # date_utc8_start = "2022-01-19"
    # date_utc8_end = "2022-01-19"
    # tracking = TrackingParser(web_id, date_utc8_start, date_utc8_end)
    #
    # df_loaded = tracking.df_loaded.sort_values(by=['timestamp'])
    # df_loaded['uuid'] = df_loaded['uuid'].astype(str)
    # df_loaded = df_loaded[df_loaded['uuid'].map(len)==36]
    # df_purchased = tracking.df_purchased
    #
    #
    #
    # uuid_load = list(set(df_loaded['uuid']))
    # uuid_purchased = list(set(df_purchased['uuid']))
    # uuid_load_len = [len(uuid) for uuid in uuid_load]
    # dict_collect_list = []
    # # keys_collect = ['uuid', 'device', 'pageviews', 'time_pageview_total', 'landing_count',
    # #                 'click_count_total', 'max_pageviews', 'max_time_pageview', 'max_time_pageview_total', 'max_scroll_depth']
    # keys_collect = ['uuid', 'pageviews', 'time_pageview_total']
    # for uuid in uuid_load:
    #     dict_collect = {}
    #     df_query = df_loaded.query(f"uuid=='{uuid}'").iloc[-1]
    #     for key in keys_collect:
    #         vlaue = df_query[key]
    #         dict_collect.update({key: vlaue})
    #         if key=='uuid':
    #             if vlaue in uuid_purchased:
    #                 dict_append = {'is_purchased': 1}
    #             else:
    #                 dict_append = {'is_purchased': 0}
    #             dict_collect.update(dict_append)
    #
    #     dict_collect_list += [dict_collect]
    # df_collect = pd.DataFrame(dict_collect_list)



    # X = np.array(df_collect)[:,2:].astype('int')
    # Y = np.array(df_collect)[:,1].astype('int')
    #
    # model = LogisticRegression(random_state=0).fit(X, Y)
    # prob = model.predict_proba(X)
    # predict = model.predict(X)
    # df_collect['prob'] = prob[:,1]
    # df_collect['predict'] = predict
    #
    # model.score(X, Y)



    # df_purchased = tracking.df_purchased
    # df_purchased_unique = df_purchased.drop(columns=['']).drop_duplicates()
    # uuid_purchased = list(set(df_purchased['uuid']))


    # data_list = tracking.data_list
    # data_list_filter = filterListofDictByDict(data_list, dict_criteria={"web_id": web_id, "event_type":"purchase"})


