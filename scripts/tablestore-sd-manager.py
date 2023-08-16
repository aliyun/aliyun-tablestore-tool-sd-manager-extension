# Copyright (c) 2024 Alibaba Group;
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import re
import sys
import time
import traceback
import uuid
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from io import BytesIO

import gradio as gr
import matplotlib.pyplot as plt
import pandas as pd
import six
from PIL import Image
from tablestore import Row, OTSClient, OTSClientError, \
    OTSServiceError, TableMeta, TableOptions, CapacityUnit, \
    ReservedThroughput, WriteRetryPolicy, FieldSchema, FieldType, AnalyzerType, SingleWordAnalyzerParameter, SearchIndexMeta, TermQuery, \
    GroupByFilter, SearchQuery, ColumnsToGet, ColumnReturnType, MatchAllQuery, Query, BoolQuery, RangeQuery, Sum, GroupByField, MatchQuery, TermsQuery, Sort, FieldSort, SortOrder
from wordcloud import WordCloud

import modules.processing as processing
import modules.scripts as scripts
from modules import script_callbacks
from modules import shared


# https://www.gradio.app/3.50.2/docs/
# noinspection PySimplifyBooleanCheck
class TablestoreHelper:

    def __init__(self) -> None:
        self.__endpoint = os.getenv("OTS_ENDPOINT_ENV")
        self.__access_key_id = os.getenv("OTS_ACCESS_KEY_ID_ENV")
        self.__access_key_secret = os.getenv("OTS_ACCESS_KEY_SECRET_ENV")
        self.__instance_name = os.getenv("OTS_INSTANCE_NAME_ENV")
        self.__region_name = self.__parse_region_from_endpoint()
        self.__table_name = "stable_diffusion_webui_plugin_tablestore_sd_manager_v1"
        self.__index_name = "%s_search_index" % self.__table_name
        self.__ots_client = OTSClient(self.__endpoint, self.__access_key_id, self.__access_key_secret, self.__instance_name, retry_policy=WriteRetryPolicy())
        self.default_max_long_value = 2147483647
        self.default_min_long_value = -1
        self.powered_by_info = f'> **表格存储(Tablestore)** 提供技术支持，[<u>点击前往控制台</u>](https://otsnext.console.aliyun.com/{self.__region_name}/{self.__instance_name}/{self.__table_name}/dataManage)'

    def __parse_region_from_endpoint(self):
        if self.__instance_name not in self.__endpoint:
            raise Exception(datetime.now(), f"Tablestore instanceName[{self.__instance_name}] must appear in endpoint[{self.__endpoint}]")
        regex_pattern = r'.*' + re.escape(self.__instance_name) + r'\.([^\.]+)'
        match = re.search(regex_pattern, self.__endpoint)
        if match:
            return match.group(1)
        else:
            raise Exception(datetime.now(), f"Parse Tablestore region info failed, please check the instance name and endpoint, your instanceName is [{self.__instance_name}], endpoint is [{self.__endpoint}]")

    def create_table_if_not_exist(self):
        table_list = self.__ots_client.list_table()
        if self.__table_name in table_list:
            print(datetime.now(), "Tablestore sd manager system table[%s] already exists" % self.__table_name)
            return None
        print(datetime.now(), "Tablestore sd manager system table[%s] does not exist, try to create the table." % self.__table_name)

        schema_of_primary_key = [('uuid', 'STRING')]
        table_meta = TableMeta(self.__table_name, schema_of_primary_key)
        table_options = TableOptions()
        reserved_throughput = ReservedThroughput(CapacityUnit(0, 0))
        try:
            self.__ots_client.create_table(table_meta, table_options, reserved_throughput)
            print(datetime.now(), "Tablestore sd manager Create table[%s] successfully." % self.__table_name)
        except OTSClientError as e:
            traceback.print_exc()
            print(datetime.now(), "Tablestore sd manager Create table[%s] failed with client error, http_status:%d, error_message:%s" % (
                self.__table_name, e.get_http_status(), e.get_error_message()), file=sys.stderr)
        except OTSServiceError as e:
            traceback.print_exc()
            print(datetime.now(),
                  "Tablestore sd manager Create table[%s] failed with service error, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (
                      self.__table_name, e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()), file=sys.stderr)

    def create_search_index_if_not_exist(self):
        search_index_list = self.__ots_client.list_search_index(table_name=self.__table_name)
        if self.__index_name in [t[1] for t in search_index_list]:
            print(datetime.now(), "Tablestore sd manager system index[%s] already exists" % self.__index_name)
            return None
        fields = [
            FieldSchema('Model', FieldType.KEYWORD, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('Version', FieldType.KEYWORD, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('Size', FieldType.KEYWORD, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('Height', FieldType.LONG, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('Width', FieldType.LONG, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('CFG scale', FieldType.DOUBLE, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('Sampler', FieldType.KEYWORD, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('Steps', FieldType.LONG, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('Prompt', FieldType.TEXT, index=True, enable_sort_and_agg=False, store=False, analyzer=AnalyzerType.SINGLEWORD, analyzer_parameter=SingleWordAnalyzerParameter(False, True)),
            FieldSchema('PromptSplits', FieldType.KEYWORD, index=True, enable_sort_and_agg=True, store=False, is_array=True),
            FieldSchema('Negative prompt', FieldType.TEXT, index=True, enable_sort_and_agg=False, store=False, analyzer=AnalyzerType.SINGLEWORD, analyzer_parameter=SingleWordAnalyzerParameter(False, True)),
            FieldSchema('NegativePromptSplits', FieldType.KEYWORD, index=True, enable_sort_and_agg=True, store=False, is_array=True),
            FieldSchema('Parameters', FieldType.TEXT, index=True, enable_sort_and_agg=False, store=False, analyzer=AnalyzerType.SINGLEWORD, analyzer_parameter=SingleWordAnalyzerParameter(False, True)),
            FieldSchema('Comments', FieldType.TEXT, index=True, enable_sort_and_agg=False, store=False, analyzer=AnalyzerType.SINGLEWORD, analyzer_parameter=SingleWordAnalyzerParameter(False, True)),
            FieldSchema('Interrupted', FieldType.BOOLEAN, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('Skipped', FieldType.BOOLEAN, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('IsTxt2Img', FieldType.BOOLEAN, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('IsImg2Img', FieldType.BOOLEAN, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('UsedTimeInSeconds', FieldType.LONG, index=True, enable_sort_and_agg=True, store=False),
            FieldSchema('JobStartTime', FieldType.DATE, index=True, enable_sort_and_agg=True, store=False, date_formats=["yyyy-MM-dd HH:mm:ss"]),
        ]
        index_meta = SearchIndexMeta(fields)
        self.__ots_client.create_search_index(self.__table_name, self.__index_name, index_meta)

    def write_one_row(self, data=None):
        primary_key = [('uuid', str(uuid.uuid4()))]
        if data is None or len(data) == 0:
            return None
        attribute_columns = []
        for k, v in data.items():
            if self.__is_reasonable_type(v):
                item = (k, v)
                attribute_columns.append(item)
            else:
                print(datetime.now(), "Tablestore sd manager find unreasonable field name:%s value:%s(%s)" % (k, v, type(v)))
        row = Row(primary_key, attribute_columns)

        try:
            self.__ots_client.put_row(self.__table_name, row)
            print(datetime.now(), "Tablestore sd manager put row successfully")
        except OTSClientError as e:
            traceback.print_exc()
            print(datetime.now(), "Tablestore sd manager put row failed with client error:%s" % e, file=sys.stderr)
        except OTSServiceError as e:
            traceback.print_exc()
            print(datetime.now(), "Tablestore sd manager put row failed with service error, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (
                e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()), file=sys.stderr)

    @staticmethod
    def __is_reasonable_type(value) -> bool:
        if value is None:
            return False
        if isinstance(value, float):
            if value == float("inf") or value == float("-inf"):
                return False
            return True
        if isinstance(value, six.text_type) or isinstance(value, bool) or isinstance(value, int):
            return True
        return False

    def img_total_count_stats(self) -> dict:
        try:
            start_time = time.perf_counter()
            search_response = self.__ots_client.search(
                table_name=self.__table_name,
                index_name=self.__index_name,
                search_query=SearchQuery(MatchAllQuery(), next_token=None, limit=0, group_bys=[
                    GroupByFilter(name="count",
                                  filters=[
                                      MatchAllQuery(),
                                      TermQuery(field_name="IsTxt2Img", column_value=True),
                                      TermQuery(field_name="IsImg2Img", column_value=True),
                                      self.__last_24h_query(MatchAllQuery()),
                                      self.__last_24h_query(TermQuery(field_name="IsTxt2Img", column_value=True)),
                                      self.__last_24h_query(TermQuery(field_name="IsImg2Img", column_value=True)),
                                  ],
                                  sub_aggs=[Sum('UsedTimeInSeconds', name='used_time_sum')])
                ]),
                columns_to_get=ColumnsToGet(return_type=ColumnReturnType.ALL_FROM_INDEX)
            )
            end_time = time.perf_counter()
            print(datetime.now(), f"Tablestore get img_total_count_stats use time: {(end_time - start_time) * 1000:.2f}ms, request_id:{search_response.request_id}")
            return {
                "total": {
                    "totalCount": search_response.group_by_results[0].items[0].row_count,
                    "totalUsedTime": search_response.group_by_results[0].items[0].sub_aggs[0].value,
                    "isTxt2ImgCount": search_response.group_by_results[0].items[1].row_count,
                    "isTxt2ImgUsedTime": search_response.group_by_results[0].items[1].sub_aggs[0].value,
                    "isImg2ImgCount": search_response.group_by_results[0].items[2].row_count,
                    "isImg2ImgUsedTime": search_response.group_by_results[0].items[2].sub_aggs[0].value,
                },
                "last24h": {
                    "totalCount": search_response.group_by_results[0].items[3].row_count,
                    "totalUsedTime": search_response.group_by_results[0].items[3].sub_aggs[0].value,
                    "isTxt2ImgCount": search_response.group_by_results[0].items[4].row_count,
                    "isTxt2ImgUsedTime": search_response.group_by_results[0].items[4].sub_aggs[0].value,
                    "isImg2ImgCount": search_response.group_by_results[0].items[5].row_count,
                    "isImg2ImgUsedTime": search_response.group_by_results[0].items[5].sub_aggs[0].value,
                }
            }
        except OTSClientError as e:
            traceback.print_exc()
            gr.Warning("Tablestore sd manager get total_count_stats with client error:%s" % e, file=sys.stderr)
        except OTSServiceError as e:
            traceback.print_exc()
            print(datetime.now(), "Tablestore sd manager get total_count_stats with service error, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()), file=sys.stderr)
            gr.Warning("Tablestore sd manager get total_count_stats with service error, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()))

    def model_stats(self) -> []:
        return self.__group_by("Model")

    def random_model_stats(self) -> []:
        return self.__random_data_frame("Model", self.__group_by("Model"))

    def negative_prompt_splits_stats(self) -> []:
        return self.__group_by("NegativePromptSplits")

    def prompt_splits_stats(self) -> []:
        return self.__group_by("PromptSplits")

    def size_stats(self) -> []:
        return self.__group_by("Size")

    def random_size_stats(self) -> []:
        return self.__random_data_frame("Size", self.__group_by("Size"))

    def sampler_stats(self) -> []:
        return self.__group_by("Sampler")

    def version_stats(self) -> []:
        return self.__group_by("Version")

    def __group_by(self, field_name: str) -> []:
        try:
            start_time = time.perf_counter()
            search_response = self.__ots_client.search(
                table_name=self.__table_name,
                index_name=self.__index_name,
                search_query=SearchQuery(MatchAllQuery(), next_token=None, limit=0, group_bys=[
                    GroupByField(field_name, size=2000)
                ]),
                columns_to_get=ColumnsToGet(return_type=ColumnReturnType.ALL_FROM_INDEX)
            )
            data = []
            for item in search_response.group_by_results[0].items:
                data.append({item.key: item.row_count})
            end_time = time.perf_counter()
            print(datetime.now(), f"Tablestore group by {field_name} use time: {(end_time - start_time) * 1000:.2f}ms, request_id:{search_response.request_id}")
            return data
        except OTSClientError as e:
            traceback.print_exc()
            gr.Warning("Tablestore sd manager group_by：%s with client error:%s" % (field_name, e), file=sys.stderr)
        except OTSServiceError as e:
            traceback.print_exc()
            print(datetime.now(), "Tablestore sd manager group_by：%s with service error, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (field_name, e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()), file=sys.stderr)
            gr.Warning("Tablestore sd manager group_by：%s with service error, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (field_name, e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()))

    @staticmethod
    def __last_24h_query(query: Query) -> Query:
        return BoolQuery(
            must_queries=[
                query,
                RangeQuery('JobStartTime', range_from=(datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"), include_lower=True),
            ],
        )

    def __delete_img_in_tablestore(self, pk):
        primary_key = [('uuid', pk)]
        row = Row(primary_key)
        try:
            self.__ots_client.delete_row(self.__table_name, row, None)
        except OTSServiceError as e:
            gr.Warning("update row failed, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()))

    @staticmethod
    def __image_exists_on_disk(img_path):
        return os.path.exists(img_path)

    def __delete_img_on_disk(self, img_path):
        if self.__image_exists_on_disk(img_path):
            os.remove(img_path)
            print(datetime.now(), f"Image[{img_path}] has been deleted.")
            gr.Info(f"Image[{img_path}] has been deleted.")
        else:
            print(datetime.now(), f"Image[{img_path}] cannot be found.")

    def search(self,
               promote_text_box,
               negative_promote_text_box,
               begin_time_box,
               end_time_box,
               model_box,
               size_box,
               is_txt_2_img_box,
               is_img_2_img_box,
               interrupted_box,
               skipped_box,
               sampler_text_box,
               version_text_box,
               min_width_box,
               max_width_box,
               min_height_box,
               max_height_box,
               min_step_box,
               max_step_box,
               min_cfg_scale_box,
               max_cfg_scale_box,
               min_used_time_box,
               max_used_time_box,
               page_size_box,
               page_number_box):
        start_time = time.perf_counter()
        bool_query = BoolQuery(must_queries=[])
        if len(promote_text_box.strip()) > 0:
            bool_query.must_queries.append(MatchQuery(field_name="Prompt", text=promote_text_box.strip()))
        if len(negative_promote_text_box.strip()) > 0:
            bool_query.must_queries.append(MatchQuery(field_name="Negative prompt", text=negative_promote_text_box.strip()))
        bool_query.must_queries.append(RangeQuery(
            field_name='JobStartTime',
            range_from=begin_time_box,
            range_to=end_time_box,
            include_lower=True,
            include_upper=True,
        ))
        if len(model_box) > 0:
            bool_query.must_queries.append(TermsQuery(field_name="Model", column_values=model_box))
        if len(size_box) > 0:
            bool_query.must_queries.append(TermsQuery(field_name="Size", column_values=size_box))
        if is_txt_2_img_box:
            bool_query.must_queries.append(TermQuery(field_name="IsTxt2Img", column_value=is_txt_2_img_box))
        if is_img_2_img_box:
            bool_query.must_queries.append(TermQuery(field_name="IsImg2Img", column_value=is_img_2_img_box))
        if interrupted_box:
            bool_query.must_queries.append(TermQuery(field_name="Interrupted", column_value=interrupted_box))
        if skipped_box:
            bool_query.must_queries.append(TermQuery(field_name="Skipped", column_value=skipped_box))
        if len(sampler_text_box) > 0:
            bool_query.must_queries.append(TermsQuery(field_name="Sampler", column_values=sampler_text_box))
        if len(version_text_box) > 0:
            bool_query.must_queries.append(TermsQuery(field_name="Version", column_values=version_text_box))
        if min_width_box == self.default_min_long_value and max_width_box == self.default_max_long_value:
            bool_query.must_queries.append(RangeQuery(
                field_name='Width',
                range_from=min_width_box,
                range_to=max_width_box,
                include_lower=True,
                include_upper=True,
            ))
        if min_height_box == self.default_min_long_value and max_height_box == self.default_max_long_value:
            bool_query.must_queries.append(RangeQuery(
                field_name='Height',
                range_from=min_height_box,
                range_to=max_height_box,
                include_lower=True,
                include_upper=True,
            ))
        if min_step_box == self.default_min_long_value and max_step_box == self.default_max_long_value:
            bool_query.must_queries.append(RangeQuery(
                field_name='Steps',
                range_from=min_step_box,
                range_to=max_step_box,
                include_lower=True,
                include_upper=True,
            ))
        if min_cfg_scale_box == self.default_min_long_value and max_cfg_scale_box == self.default_max_long_value:
            bool_query.must_queries.append(RangeQuery(
                field_name='CFG scale',
                range_from=min_cfg_scale_box,
                range_to=max_cfg_scale_box,
                include_lower=True,
                include_upper=True,
            ))
        if min_used_time_box == self.default_min_long_value and max_used_time_box == self.default_max_long_value:
            bool_query.must_queries.append(RangeQuery(
                field_name='UsedTimeInSeconds',
                range_from=min_used_time_box,
                range_to=max_used_time_box,
                include_lower=True,
                include_upper=True,
            ))

        try:
            search_response = self.__ots_client.search(
                table_name=self.__table_name,
                index_name=self.__index_name,
                search_query=SearchQuery(
                    query=bool_query,
                    limit=int(page_size_box),
                    offset=int(page_number_box) * int(page_size_box),
                    sort=Sort(sorters=[FieldSort(field_name="JobStartTime", sort_order=SortOrder.DESC)]),
                    get_total_count=True,
                ),
                columns_to_get=ColumnsToGet(return_type=ColumnReturnType.ALL)
            )
            keys = [
                "Model",
                "Prompt",
                "Negative prompt",
                "Parameters",
                "Steps",
                "CFG scale",
                "Size",
                "Height",
                "Width",
                "Seed",
                "Sampler",
                "Comments",
                "Version",
                "UsedTimeInSeconds",
                "JobStartTime",
                "ImagePath",
                "Model hash",
                "IsImg2Img",
                "IsTxt2Img",
                "Skipped",
                "Interrupted"
            ]
            data_list = []
            for row in search_response.rows:
                data = {"uuid": row[0][0][1]}
                columns = row[1]
                for col in columns:
                    key = col[0]
                    if key in keys:
                        if key in ["Steps", "Height", "Width", "Seed", "UsedTimeInSeconds"]:
                            data[col[0]] = int(col[1])
                        else:
                            data[col[0]] = col[1]
                data_list.append(data)
            end_time = time.perf_counter()
            print(datetime.now(), f"Tablestore search hit total:{search_response.total_count}, request_id:{search_response.request_id}, use time: {(end_time - start_time) * 1000:.2f}ms")
            gallery_data = []
            for data_item in data_list:
                img_path = data_item["ImagePath"]
                pk_uuid = data_item["uuid"]
                if not self.__image_exists_on_disk(img_path):
                    self.__delete_img_in_tablestore(pk_uuid)
                    gr.Warning(f"Image[{img_path}] cannot be found on the disk and will be deleted from the Tablestore.")
                    continue
                gallery_data.append((img_path, data_item))

            if len(gallery_data) == 0:
                if search_response.total_count > 0:
                    ext_text = f" ,请在更多查询条件里调整**页数**为合理参数才可以正常显示，当前第 **{int(page_number_box)}** 页，每页展示 **{int(page_size_box)}** 张"
                else:
                    ext_text = ""
                return [
                    gr.Gallery.update(visible=False),
                    gr.Markdown.update(visible=False),
                    gr.Textbox.update(""),
                    gr.Button.update(visible=False),
                    f"> 找到 **{search_response.total_count}** 张图片{ext_text}",
                ]
            else:
                return [
                    gr.Gallery.update(gallery_data, visible=True),
                    gr.Markdown.update(self.__img_markdown(gallery_data[0][1]), visible=True),
                    gr.Textbox.update(json.dumps(gallery_data[0][1], ensure_ascii=True)),
                    gr.Button.update(visible=True),
                    f"> 找到 **{search_response.total_count}** 张图片，第 **{int(page_number_box)}** 页，每页展示 **{int(page_size_box)}** 张",
                ]
        except OTSClientError as e:
            gr.Warning("Tablestore sd manager search with client error:%s" % e, file=sys.stderr)
            traceback.print_exc()
        except OTSServiceError as e:
            gr.Warning("Tablestore sd manager search with service error, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()))
            traceback.print_exc()
            print(datetime.now(), "Tablestore sd manager search with service error, http_status:%d, error_code:%s, error_message:%s, request_id:%s" % (e.get_http_status(), e.get_error_code(), e.get_error_message(), e.get_request_id()), file=sys.stderr)
        return [None, None, None, None, None]

    @staticmethod
    def __dict_list_to_dict(dict_list: list) -> dict:
        result = {}
        for sub_dict in dict_list:
            result.update(sub_dict)
        return result

    @staticmethod
    def __random_data_frame(x_name: str, data: list):
        data_sorted = sorted(data, key=lambda x: list(x.keys())[0])
        x_value = [list(item.keys())[0] for item in data_sorted]
        count = [list(item.values())[0] for item in data_sorted]
        return pd.DataFrame(
            {
                x_name: x_value,
                "Count": count,
            }
        )

    def create_promote_word_cloud_img(self):
        return self.__create_word_cloud_img(self.prompt_splits_stats())

    def create_negative_promote_word_cloud_img(self):
        return self.__create_word_cloud_img(self.negative_prompt_splits_stats())

    def update_word_cloud_img(self):
        return self.create_promote_word_cloud_img(), self.create_negative_promote_word_cloud_img()

    def update_search_tab(self):
        result = [
            gr.Dropdown.update(choices=[list(item.keys())[0] for item in self.model_stats()]),
            gr.Dropdown.update(choices=[list(item.keys())[0] for item in self.size_stats()]),
            gr.Dropdown.update(choices=[list(item.keys())[0] for item in self.sampler_stats()]),
            gr.Dropdown.update(choices=[list(item.keys())[0] for item in self.version_stats()]),
        ]
        return result

    def __create_word_cloud_img(self, dict_list: list) -> Image:
        if len(dict_list) == 0:
            dict_list = [{"Emtpy": 10}]
        word_cloud_ins = WordCloud(width=768 * 2, height=768, background_color='white').generate_from_frequencies(self.__dict_list_to_dict(dict_list))
        plt.figure(figsize=(10, 5))
        plt.imshow(word_cloud_ins, interpolation='spline36')
        plt.axis('off')
        buf = BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        image = Image.open(buf)
        return image

    def on_delete_img(self, data_str, gallery_box):
        json_data = json.loads(data_str)
        print(datetime.now(), f"Tablestore try to delete image info:{data_str}")
        pk = json_data['uuid']
        img_path = json_data['ImagePath']
        self.__delete_img_in_tablestore(pk)
        self.__delete_img_on_disk(img_path)
        new_gallery_box = []
        for item in gallery_box:
            if item[1]["uuid"] == pk:
                continue
            new_gallery_box.append((item[1]["ImagePath"], item[1]))
        if len(new_gallery_box) > 0:
            return [
                gr.Gallery.update(new_gallery_box, visible=True),
                gr.Markdown.update(self.__img_markdown(new_gallery_box[0][1]), visible=True),
                gr.Textbox.update(json.dumps(new_gallery_box[0][1], ensure_ascii=True)),
                gr.Button.update(visible=True),
            ]
        else:
            return [
                gr.Gallery.update(visible=False),
                gr.Markdown.update(visible=False),
                gr.Textbox.update(""),
                gr.Button.update(visible=False),
            ]

    @staticmethod
    def __img_markdown(img_data):
        keys = [
            "Model",
            "Prompt",
            "Negative prompt",
            "Steps",
            "CFG scale",
            "Size",
            "Height",
            "Width",
            "Seed",
            "Sampler",
            "Comments",
            "Version",
            "UsedTimeInSeconds",
            "JobStartTime",
            "ImagePath",
            "Model hash",
            "IsImg2Img",
            "IsTxt2Img",
            "Parameters",
        ]
        result = ""
        for key in keys:
            if key in img_data:
                img_data_item = img_data[key]
                if type(img_data_item) is str:
                    img_data_item = img_data_item.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
                result += f' - **{key}**: &nbsp; {img_data_item}\r\n'
        return result

    def on_gallery_box_select(self, evt: gr.SelectData):
        return self.__img_markdown(evt.value), json.dumps(evt.value, ensure_ascii=True)

    @staticmethod
    def img_stats_html():
        img_stats = tablestoreHelper.img_total_count_stats()
        return f'''
        <div class="tablestore_row">
            <div class="tablestore_column" style="flex: 5;">
                <div class="tablestore_row tablestore_compact">
                    <div class="tablestore_column" style="flex: 5; min-width: 20px;">
                        <h4>历史统计</h4>
                    </div>
                    <div class="tablestore_column" style="flex: 5; min-width: 20px;">
                        <p>图片数: <span class="tablestore_strong">{img_stats["total"]["totalCount"]}</span></p>
                        <br>
                        <p>耗时: <span class="tablestore_strong">{img_stats["total"]["totalUsedTime"]} 秒</span></p>
                    </div>
                    <div class="tablestore_column" style="flex: 5; min-width: 20px;">
                        <p>文生图数: <span class="tablestore_strong">{img_stats["total"]["isTxt2ImgCount"]}</span></p>
                        <br>
                        <p>文生图耗时: <span class="tablestore_strong">{img_stats["total"]["isTxt2ImgUsedTime"]} 秒</span></p>
                    </div>
                    <div class="tablestore_column" style="flex: 5; min-width: 20px;">
                        <p>图生图数: <span class="tablestore_strong">{img_stats["total"]["isImg2ImgCount"]}</span></p>
                        <br>
                        <p>图生图耗时: <span class="tablestore_strong">{img_stats["total"]["isImg2ImgUsedTime"]} 秒</span></p>
                    </div>
                </div>
            </div>
            <div class="tablestore_column" style="flex: 5;">
                <div class="tablestore_row tablestore_compact">
                    <div class="tablestore_column" style="flex: 5; min-width: 20px;">
                        <h4>最近一天统计</h4>
                    </div>
                    <div class="tablestore_column" style="flex: 5; min-width: 20px;">
                        <p>图片数: <span class="tablestore_strong">{img_stats["last24h"]["totalCount"]}</span></p>
                        <br>
                        <p>耗时: <span class="tablestore_strong">{img_stats["last24h"]["totalUsedTime"]} 秒</span></p>
                    </div>
                    <div class="tablestore_column" style="flex: 5; min-width: 20px;">
                        <p>文生图数: <span class="tablestore_strong">{img_stats["last24h"]["isTxt2ImgCount"]}</span></p>
                        <br>
                        <p>文生图耗时: <span class="tablestore_strong">{img_stats["last24h"]["isTxt2ImgUsedTime"]} 秒</span></p>
                    </div>
                    <div class="tablestore_column" style="flex: 5; min-width: 20px;">
                        <p>图生图数: <span class="tablestore_strong">{img_stats["last24h"]["isImg2ImgCount"]}</span></p>
                        <br>
                        <p>图生图耗时: <span class="tablestore_strong">{img_stats["last24h"]["isImg2ImgUsedTime"]} 秒</span></p>
                    </div>
                </div>
            </div>
        </div>
        '''


tablestoreHelper = TablestoreHelper()
print(datetime.now(), "--> Start initializing tablestore-sd-manager-extension")
tablestoreHelper.create_table_if_not_exist()
tablestoreHelper.create_search_index_if_not_exist()
print(datetime.now(), "--> Finish initializing tablestore-sd-manager-extension")


def on_ui_tabs():
    with gr.Blocks(css="style.css") as tablestore:
        with gr.Tab("概览") as overview_tab:
            with gr.Row():
                gr.HTML(value=tablestoreHelper.img_stats_html, every=10)
            with gr.Row(variant="panel"):
                with gr.Column(scale=5):
                    gr.BarPlot(
                        value=tablestoreHelper.random_model_stats,
                        x="Model",
                        y="Count",
                        label="模型统计分布",
                        tooltip=["Model", "Count"],
                        scale=5,
                        every=60,
                    )
                with gr.Column(scale=5):
                    gr.BarPlot(
                        value=tablestoreHelper.random_size_stats,
                        x="Size",
                        y="Count",
                        label="图片大小分布",
                        tooltip=["Size", "Count"],
                        scale=5,
                        every=60,
                    )
            with gr.Row(variant="panel"):
                with gr.Column(scale=5):
                    promote_word_cloud_box = gr.Image(label="Prompt词云", value=tablestoreHelper.create_promote_word_cloud_img())
                with gr.Column(scale=5):
                    negative_promote_word_cloud_box = gr.Image(label="NegativePrompt词云", value=tablestoreHelper.create_negative_promote_word_cloud_img())
                overview_tab.select.trigger_only_on_success = True
                overview_tab.select(tablestoreHelper.update_word_cloud_img, None, [promote_word_cloud_box, negative_promote_word_cloud_box])
        with gr.Tab("图片查询") as search_tab:
            search_tab.select.trigger_only_on_success = True
            with gr.Row():
                with gr.Row():
                    promote_text_box = gr.Textbox(label='Promote', interactive=True, value="")
                    negative_promote_text_box = gr.Textbox(label='NegativePromote', interactive=True, value="")
                with gr.Row():
                    begin_time_box = gr.Textbox(label='BeginTime', value=(datetime.now() - timedelta(hours=24 * 3)).strftime("%Y-%m-%d %H:%M:%S"), interactive=True)
                    end_time_box = gr.Textbox(label='EndTime', value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), interactive=True)
            with gr.Row():
                with gr.Column(scale=5):
                    model_box = gr.Dropdown(label='Model', multiselect=True, allow_custom_value=False)
                with gr.Column(scale=5):
                    size_box = gr.Dropdown(label='Size', multiselect=True, allow_custom_value=False)

            with gr.Accordion("点击选择更多条件", open=False):
                with gr.Row():
                    with gr.Column(scale=1, min_width=20):
                        is_txt_2_img_box = gr.Checkbox(label='isTxt2Img', min_width=20)
                    with gr.Column(scale=1, min_width=20):
                        is_img_2_img_box = gr.Checkbox(label='isImg2Img', min_width=20)
                    with gr.Column(scale=1, min_width=20):
                        interrupted_box = gr.Checkbox(label='interrupted', min_width=20)
                    with gr.Column(scale=1, min_width=20):
                        skipped_box = gr.Checkbox(label='skipped', min_width=20)
                with gr.Row():
                    sampler_text_box = gr.Dropdown(label='Sampler', multiselect=True, allow_custom_value=False)
                    version_text_box = gr.Dropdown(label='Version', multiselect=True, allow_custom_value=False)
                with gr.Row():
                    with gr.Column(scale=1, min_width=20):
                        with gr.Tab(label="Width"):
                            min_width_box = gr.Number(label='Min Width', value=tablestoreHelper.default_min_long_value, interactive=True, min_width=20)
                            max_width_box = gr.Number(label='Max Width', value=tablestoreHelper.default_max_long_value, interactive=True, min_width=20)
                    with gr.Column(scale=1, min_width=20):
                        with gr.Tab(label="Height"):
                            min_height_box = gr.Number(label='Min Height', value=tablestoreHelper.default_min_long_value, interactive=True, min_width=20)
                            max_height_box = gr.Number(label='Max Height', value=tablestoreHelper.default_max_long_value, interactive=True, min_width=20)
                    with gr.Column(scale=1, min_width=20):
                        with gr.Tab(label="Steps"):
                            min_step_box = gr.Number(label='Min Steps', value=tablestoreHelper.default_min_long_value, interactive=True, min_width=20)
                            max_step_box = gr.Number(label='Max Steps', value=tablestoreHelper.default_max_long_value, interactive=True, min_width=20)
                    with gr.Column(scale=1, min_width=20):
                        with gr.Tab(label="CFG scale"):
                            min_cfg_scale_box = gr.Number(label='Min CFG Scale', value=tablestoreHelper.default_min_long_value, interactive=True, min_width=20)
                            max_cfg_scale_box = gr.Number(label='Max CFG Scale', value=tablestoreHelper.default_max_long_value, interactive=True, min_width=20)
                    with gr.Column(scale=1, min_width=20):
                        with gr.Tab(label="生成耗时"):
                            min_used_time_box = gr.Number(label='Min UsedTime(Seconds)', value=tablestoreHelper.default_min_long_value, interactive=True, min_width=20)
                            max_used_time_box = gr.Number(label='Max UsedTime(Seconds)', value=tablestoreHelper.default_max_long_value, interactive=True, min_width=20)
                with gr.Row():
                    with gr.Column(scale=1, min_width=20):
                        page_size_box = gr.Number(label='每页显示', value=20, interactive=True, min_width=20, maximum=100, minimum=0)
                    with gr.Column(scale=1, min_width=20):
                        page_number_box = gr.Number(label='第几页', value=0, interactive=True, min_width=20, minimum=0)
            search_tab.select(tablestoreHelper.update_search_tab, [], [model_box, size_box, sampler_text_box, version_text_box])
            with gr.Row():
                search_button = gr.Button(value="查询", variant='primary')

            with gr.Row():
                with gr.Column(min_width=20):
                    gr.Markdown(tablestoreHelper.powered_by_info)
                with gr.Column(min_width=20):
                    total_count = gr.Markdown()
            with gr.Row():
                with gr.Column(scale=8):
                    gallery_box = gr.Gallery(height=900, columns=4, preview=False, show_label=False, allow_preview=True, visible=False, show_download_button=False, elem_classes="tablestore_gallery_box")
                with gr.Column(scale=2):
                    with gr.Row(variant="panel"):
                        md_box = gr.Markdown(visible=False, elem_classes="tablestore_image_detail")
                        json_box = gr.Textbox(visible=False)
                    with gr.Row():
                        delete_button = gr.Button(value="删除选中图片", visible=False, variant="stop")
                        delete_button.click(fn=tablestoreHelper.on_delete_img, inputs=[json_box, gallery_box], outputs=[gallery_box, md_box, json_box, delete_button])
                gallery_box.select(tablestoreHelper.on_gallery_box_select, [], [md_box, json_box])

            search_button.click(tablestoreHelper.search, inputs=[
                promote_text_box,
                negative_promote_text_box,
                begin_time_box,
                end_time_box,
                model_box,
                size_box,
                is_txt_2_img_box,
                is_img_2_img_box,
                interrupted_box,
                skipped_box,
                sampler_text_box,
                version_text_box,
                min_width_box,
                max_width_box,
                min_height_box,
                max_height_box,
                min_step_box,
                max_step_box,
                min_cfg_scale_box,
                max_cfg_scale_box,
                min_used_time_box,
                max_used_time_box,
                page_size_box,
                page_number_box,
            ], outputs=[gallery_box, md_box, json_box, delete_button, total_count])
    return [(tablestore, "图片管理", "tablestore")]


script_callbacks.on_ui_tabs(on_ui_tabs)


# noinspection PyMethodMayBeStatic,DuplicatedCode,PyBroadException,PyMethodOverriding
class Scripts(scripts.Script):

    def __init__(self) -> None:
        super().__init__()
        self.__re_param_code = r'\s*([\w ]+):\s*("(?:\\"[^,]|\\"|\\|[^\"])+"|[^,]*)(?:,|$)'
        self.__re_param = re.compile(self.__re_param_code)
        self.__re_imagesize = re.compile(r"^(\d+)x(\d+)$")

    def title(self):
        return "tablestore-sd-manager"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        return []

    def postprocess(self, p: processing.StableDiffusionProcessing, processed: processing.Processed):
        try:
            for index, image in enumerate(processed.images):
                try:
                    data = dict()
                    data["Interrupted"] = shared.state.interrupted
                    data["Skipped"] = shared.state.skipped
                    data["IsTxt2Img"] = self.is_txt2img
                    data["IsImg2Img"] = self.is_img2img
                    data['Comments'] = getattr(processed, 'comments', None)
                    job_timestamp = datetime.strptime(processed.job_timestamp, '%Y%m%d%H%M%S')
                    data['UsedTimeInSeconds'] = round(datetime.now().timestamp() - job_timestamp.timestamp())
                    data['JobStartTime'] = job_timestamp.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    already_saved_as = getattr(image, 'already_saved_as', None)
                    if type(already_saved_as) is not str:
                        print(datetime.now(), "Tablestore sd extension already_saved_as isn't string, data:", data)
                        continue
                    if already_saved_as.startswith("/"):
                        data['ImagePath'] = already_saved_as
                    else:
                        data['ImagePath'] = "%s/%s" % (scripts.shared.data_path, already_saved_as) if already_saved_as is not None else None
                    data['Parameters'] = image.info['parameters']
                    all_parameters = self.__parse_parameters(data['Parameters'])
                    data.update(all_parameters)
                    for key in list(data.keys()):
                        try:
                            if key in ["Height", "Width", "Seed", "Steps"]:
                                data[key] = int(data[key])
                            if key == "CFG scale":
                                data[key] = float(data[key])
                            if key == "Prompt":
                                data["PromptSplits"] = self.__splits_as_json_array_string(data[key])
                            if key == "Negative prompt":
                                data["NegativePromptSplits"] = self.__splits_as_json_array_string(data[key])
                        except Exception as e:
                            print(datetime.now(), f"Tablestore sd extension value error: cannot convert dictionary key'{key}' value '{data[key]}'", e)

                    data_as_str = json.dumps(data, ensure_ascii=False, indent=4)
                    print(datetime.now(), "\nTablestore write data", data_as_str)
                    tablestoreHelper.write_one_row(data)
                except Exception as e:
                    print(datetime.now(), "Tablestore sd extension get image info error", e)
                    traceback.print_exc()
        except Exception as e:
            print(datetime.now(), "Tablestore sd extension error", e)
            traceback.print_exc()
        return

    def __splits_as_json_array_string(self, s: str) -> str:
        tokens = [token.strip() for token in re.split(r'[ ,]+', s) if token.strip()]
        json_string = json.dumps(tokens)
        return json_string

    def __unquote(self, text):
        if len(text) == 0 or text[0] != '"' or text[-1] != '"':
            return text
        try:
            return json.loads(text)
        except Exception:
            return text

    def __parse_parameters(self, x: str) -> dict:
        res = dict()

        prompt = ""
        negative_prompt = ""

        done_with_prompt = False

        *lines, lastline = x.strip().split("\n")
        if len(self.__re_param.findall(lastline)) < 3:
            lines.append(lastline)
            lastline = ''

        for line in lines:
            line = line.strip()
            if line.startswith("Negative prompt:"):
                done_with_prompt = True
                line = line[16:].strip()
            if done_with_prompt:
                negative_prompt += ("" if negative_prompt == "" else "\n") + line
            else:
                prompt += ("" if prompt == "" else "\n") + line

        res["Prompt"] = prompt
        res["Negative prompt"] = negative_prompt

        for k, v in self.__re_param.findall(lastline):
            try:
                if v[0] == '"' and v[-1] == '"':
                    v = self.__unquote(v)

                m = self.__re_imagesize.match(v)
                if m is not None:
                    res[f"Width"] = m.group(1)
                    res[f"Height"] = m.group(2)
                res[k] = v
            except Exception as e:
                print(datetime.now(), f"Error parsing \"{k}: {v}\"", e)
        return res
