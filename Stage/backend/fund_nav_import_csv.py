import pandas as pd
from sqlalchemy.types import String, Date, FLOAT, Integer
from config_fh import get_db_session, get_db_engine, STR_FORMAT_DATE
import os
from fh_tools.fh_utils import str_2_date, get_first, pattern_data_format, try_2_date
import xlrd
import logging
logger = logging.getLogger()


def update_fundnav_by_csv2(file_path, mode='delete_insert'):
    df = pd.read_csv(file_path)
    df.set_index('nav_date_week', inplace=True)
    df_fund = df.unstack().reset_index().dropna()
    col_name_list = list(df_fund.columns)
    df_fund.rename(columns={col_name_list[0]: 'wind_code', col_name_list[1]: 'nav_date', col_name_list[2]: 'nav'},
                   inplace=True)
    df_fund[['trade_date', 'nav_acc']] = df_fund[['nav_date', 'nav']]
    if mode == 'delete_insert':
        df_fund.set_index(['wind_code', 'trade_date'], inplace=True)
        # df_fund['nav_acc'] = df_fund['nav']
        table_name = 'fund_nav_tmp'

        sql_str = 'delete from fund_nav_tmp where wind_code in (%s)' % ("'" + "', '".join(df.columns) + "'")
        engine = get_db_engine()
        with get_db_session(engine) as session:
            session.execute(sql_str)
        df_fund.to_sql(table_name, engine, if_exists='append',
                       dtype={
                           'wind_code': String(20),
                           'trade_date': Date,
                           'nav_date': Date,
                           'nav': FLOAT,
                           'nav_acc': FLOAT,
                       })
    elif mode == 'replace_insert':
        data_list = list(df_fund.T.to_dict().values())
        sql_str = "REPLACE INTO fund_nav_tmp (wind_code, trade_date, nav, nav_acc, nav_date) values (:wind_code, :trade_date, :nav, :nav_acc, :nav_date)"
        with get_db_session() as session:
            session.execute(sql_str, data_list)
            pass
    else:
        raise ValueError('mode="%s" is not available' % mode)


def fund_nav_df_fillna(fund_nav_df):
    """
    为 fund_nav_df 补充nav数据并记录错误日志 
    :param fund_nav_df: 
    :return: 
    """
    fund_nav_df.dropna(subset=['nav'], inplace=True)
    fund_nav_df['nav_acc'] = fund_nav_df[['nav', 'nav_acc']].fillna(method='ffill', axis=1)['nav_acc']
    return fund_nav_df


def update_fundnav_by_file(wind_code, file_path, mode='delete_insert', skip_rows=0, sheet_name=0):
    """
    支持 csv xls xlsx 文件格式导入 fund_nav表 
    :param wind_code: 
    :param file_path: 
    :param mode: 'replace_insert' 更新或插入；
    'delete_insert' 删除时期段内的数据并插入；
    'remove_insert' 移除全部历史数据并插入；
    :return: 
    """
    _, file_extension = os.path.splitext(file_path)
    if file_extension == '.csv':
        fund_nav_df = pd.read_csv(file_path)
    elif file_extension in ('.xls', '.xlsx'):
        fund_nav_df = pd.read_excel(file_path, skiprows=skip_rows, sheetname=sheet_name)
    else:
        raise ValueError('不支持 %s 净值文件类型' % file_extension)
    col_name_list = list(fund_nav_df.columns)
    if len(col_name_list) == 2:
        fund_nav_df['nav_acc'] = fund_nav_df[col_name_list[1]]
        col_name_list = list(fund_nav_df.columns)
    fund_nav_df.rename(columns={col_name_list[0]: 'nav_date', col_name_list[1]: 'nav', col_name_list[2]: 'nav_acc'},
                       inplace=True)
    fund_nav_df = fund_nav_df_fillna(fund_nav_df)
    fund_nav_df['wind_code'] = wind_code
    fund_nav_df['source_mark'] = 2
    # lambda x: datetime.strptime(x, STR_FORMAT_DATE)
    data_str = get_first(fund_nav_df['nav_date'], lambda x: type(x) == str)
    if data_str is not None:
        date_str_format = pattern_data_format(data_str)
        fund_nav_df['nav_date'] = fund_nav_df['nav_date'].apply(
            lambda x: str_2_date(x, date_str_format=date_str_format))
    else:
        fund_nav_df['nav_date'] = fund_nav_df['nav_date'].apply(try_2_date)
    # 更新数据库
    engine = get_db_engine()
    if mode == 'delete_insert':
        nav_date_s = fund_nav_df['nav_date']
        if nav_date_s.shape[0] > 0:
            date_min, date_max = try_2_date(nav_date_s.min()), try_2_date(nav_date_s.max())
            sql_str = 'delete from fund_nav where wind_code = :wind_code and nav_date between :date_frm and :date_to'
            with get_db_session(engine) as session:
                session.execute(sql_str, [{'wind_code': wind_code,
                                           'date_frm': date_min,
                                           'date_to': date_max}])

        table_name = 'fund_nav'
        fund_nav_df.set_index(['wind_code', 'nav_date'], inplace=True)
        fund_nav_df.to_sql(table_name, engine, if_exists='append',
                           dtype={
                               'wind_code': String(20),
                               'nav_date': Date,
                               'nav': FLOAT,
                               'nav_acc': FLOAT,
                               'source_mark': Integer
                           })
    elif mode == 'remove_insert':
        sql_str = 'delete from fund_nav where wind_code = :wind_code'
        with get_db_session(engine) as session:
            session.execute(sql_str, [{'wind_code': wind_code}])
        table_name = 'fund_nav'
        fund_nav_df.set_index(['wind_code', 'nav_date'], inplace=True)
        fund_nav_df.to_sql(table_name, engine, if_exists='append',
                           dtype={
                               'wind_code': String(20),
                               'nav_date': Date,
                               'nav': FLOAT,
                               'nav_acc': FLOAT,
                               'source_mark': Integer
                           })
    elif mode == 'replace_insert':
        data_list = list(fund_nav_df.T.to_dict().values())
        sql_str = "REPLACE INTO fund_nav (wind_code, nav_date, nav, nav_acc, source_mark) values (:wind_code, :nav_date, :nav, :nav_acc, :source_mark)"
        with get_db_session() as session:
            session.execute(sql_str, data_list)
    else:
        raise ValueError('mode="%s" is not available' % mode)
    sql_str = "call proc_update_fund_info_by_wind_code2(:wind_code, :force_update)"
    with get_db_session(engine) as session:
        session.execute(sql_str, {'wind_code': wind_code, 'force_update': True})
    logger.info('import fund_nav %d data on %s' % (fund_nav_df.shape[0], wind_code))


# def update_fundnav_by_file(wind_code, file_path, mode='replace_insert', skip_rows=0, sheet_name=0):
#     """
#     支持 csv xls xlsx 文件格式导入 fund_nav表
#     :param wind_code:
#     :param file_path:
#     :param mode: 'replace_insert' 'replace_insert'
#     :return:
#     """
#     _, file_extension = os.path.splitext(file_path)
#     if file_extension == '.csv':
#         fund_nav_df = pd.read_csv(file_path)
#     elif file_extension in ('.xls', '.xlsx'):
#         fund_nav_df = pd.read_excel(file_path, skiprows=skip_rows, sheetname=sheet_name)
#     else:
#         raise ValueError('不支持 %s 净值文件类型' % file_extension)
#     col_name_list = list(fund_nav_df.columns)
#     if len(col_name_list) == 2:
#         fund_nav_df['nav_acc'] = fund_nav_df[col_name_list[1]]
#         col_name_list = list(fund_nav_df.columns)
#     fund_nav_df.rename(columns={col_name_list[0]: 'nav_date', col_name_list[1]: 'nav', col_name_list[2]: 'nav_acc'},
#                        inplace=True)
#     fund_nav_df = fund_nav_df_fillna(fund_nav_df)
#     fund_nav_df['wind_code'] = wind_code
#     fund_nav_df['source_mark'] = 2
#     # lambda x: datetime.strptime(x, STR_FORMAT_DATE)
#     data_str = get_first(fund_nav_df['nav_date'], lambda x: type(x) == str)
#     if data_str is not None:
#         date_str_format = pattern_data_format(data_str)
#         fund_nav_df['nav_date'] = fund_nav_df['nav_date'].apply(lambda x: str_2_date(x, date_str_format=date_str_format))
#     else:
#         fund_nav_df['nav_date'] = fund_nav_df['nav_date'].apply(try_2_date)
#     if mode == 'delete_insert':
#         fund_nav_df.set_index(['wind_code', 'nav_date'], inplace=True)
#         sql_str = 'delete from fund_nav where wind_code = :wind_code'
#         engine = get_db_engine()
#         with get_db_session(engine) as session:
#             session.execute(sql_str, [{'wind_code': wind_code}])
#         table_name = 'fund_nav'
#         fund_nav_df.to_sql(table_name, engine, if_exists='append',
#                            dtype={
#                            'wind_code': String(20),
#                            'nav_date': Date,
#                            'nav': FLOAT,
#                            'nav_acc': FLOAT,
#                            'source_mark': Integer
#                        })
#     elif mode == 'replace_insert':
#         data_list = list(fund_nav_df.T.to_dict().values())
#         sql_str = "REPLACE INTO fund_nav (wind_code, nav_date, nav, nav_acc, source_mark) values (:wind_code, :nav_date, :nav, :nav_acc, :source_mark)"
#         with get_db_session() as session:
#             session.execute(sql_str, data_list)
#     else:
#         raise ValueError('mode="%s" is not available' % mode)
#
#     sql_str = "call proc_update_fund_info_by_wind_code2(:wind_code, :force_update)"
#     with get_db_session() as session:
#         session.execute(sql_str, {'wind_code': wind_code, 'force_update': True})
#     print('import fund_nav %d data on %s' % (fund_nav_df.shape[0], wind_code))


def update_fundnav_by_sheet_name(wind_code_sheet_name_dic_list, file_path, mode='replace_insert', skip_rows=0):
    """
    支持 csv xls xlsx 文件格式导入 fund_nav表 
    :param wind_code: 
    :param file_path: 
    :param mode: 'replace_insert' 'replace_insert'
    :return: 
    """
    _, file_extension = os.path.splitext(file_path)
    xls_data = xlrd.open_workbook(file_path)  # 打开xls文件
    name_list = xls_data.sheet_names()
    for wind_code_sheet_name_dic in wind_code_sheet_name_dic_list:
        wind_code = wind_code_sheet_name_dic['wind_code']
        sheet_name = wind_code_sheet_name_dic['sheet_name']
        index_sheet = name_list.index(sheet_name)
        update_fundnav_by_file(wind_code, file_path, mode=mode, skip_rows=skip_rows, sheet_name=index_sheet)


def import_fund_nav_fof1(file_path):
    wind_code_sheet_name_dic_list = [
        {'wind_code': 'FHF-101701', 'sheet_name': 'FHF-101601'},
        {'wind_code': 'XT1614159.XT', 'sheet_name': 'FHF-101601A'},  # 盛世复华汉武1号私募基金
        {'wind_code': 'XT1605537.XT', 'sheet_name': 'FHF-101601B'},  # 杉树欣欣
        {'wind_code': 'FHF-101601C', 'sheet_name': 'FHF-101601C'},  # 九坤量化阿尔法1号私募基金
        {'wind_code': 'XT1614142.XT', 'sheet_name': 'FHF-101601D'},  # 宽投复华1号CTA私募基金
        {'wind_code': 'XT1612348.XT', 'sheet_name': 'FHF-101601E'},  # 开拓者-复华-量化CTA私募基金
    ]
    update_fundnav_by_sheet_name(wind_code_sheet_name_dic_list, file_path, mode='replace_insert', skip_rows=1)


def import_fund_nav_fof2(file_path):
    wind_code_sheet_name_dic_list = [
        {'wind_code': 'FHF-101701', 'sheet_name': 'FHF-101701'},
        {'wind_code': 'FHF-101701C', 'sheet_name': 'FHF-101701C'},  # 因诺天机17号私募基金
        {'wind_code': 'FHF-101701D', 'sheet_name': 'FHF-101701D'},  # 新萌复华1号CTA私募基金
        {'wind_code': 'FHF-101701E', 'sheet_name': 'FHF-101701E'},  # 千象全景1号
    ]
    update_fundnav_by_sheet_name(wind_code_sheet_name_dic_list, file_path, mode='replace_insert', skip_rows=1)
    # update_fundnav_by_sheet_name(wind_code_sheet_name_dic_list, file_path, mode='delete_insert', skip_rows=1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s: %(levelname)s [%(name)s] %(message)s')
    # file_path = r'd:\Downloads\nav_file.xlsx'
    # 'XT1522529.XT' 明溪1号
    # file_path = 'd:\Downloads\FOF一期净值.xlsx'
    # replace_insert delete_insert

    # wind_code = 'XT1612348.XT'
    # file_path = r'd:\Works\F复华投资\L路演、访谈、评估报告\开拓者-复华-量化CTA私募基金【每日净值20170428】.xlsx'

    # 文件上传方式更新基金净值
    # wind_code = 'XT1605537.XT'
    # file_path = r'd:\Works\F复华投资\L路演、访谈、评估报告\杉树欣欣 2017-05-16.xlsx'
    wind_code = 'FHF-P-101602'
    file_path = r'd:\Downloads\大客户2专项理财计划.csv'
    update_fundnav_by_file(wind_code, file_path)  # , mode='replace_insert'

    # 鑫隆FOF 一期、二期净值
    # wind_code = 'FHF101601'
    # wind_code = 'FHB101701'

    # file_path = r"Z:\投后管理\产品净值\FOF基金\产品净值\FOF二期净值.xlsx"
    # import_fund_nav_fof2(file_path)

    # file_path = r"Z:\投后管理\产品净值\FOF基金\产品净值\FOF一期净值.xlsx"
    # import_fund_nav_fof1(file_path)
