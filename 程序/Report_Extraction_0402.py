from flask import Flask, request, Response, jsonify
import os
import json
import re
import tempfile
import shutil
import urllib.parse
from minio import Minio
from pdf2image import convert_from_path
from werkzeug.utils import secure_filename
from openai import OpenAI
from flask_cors import CORS
import pymysql
from aip import AipOcr
import configparser
from PIL import Image, ImageDraw, ImageFont
import subprocess
import uuid
import requests
from urllib.parse import urlparse
from io import BytesIO


def run_sql(query):
    conf = {'host': '39.106.184.170', 'port': '3306', 'user': 'bamboo', 'database': 'test_dev', 'passwd': 'chenshi0201',
            'charset': 'utf8'}
    try:
        connection = pymysql.connect(
            host=conf['host'],
            port=int(conf['port']),
            user=conf['user'],
            password=conf['passwd'],
            database=conf['database'],
            charset=conf['charset'],
            cursorclass=pymysql.cursors.DictCursor
        )

        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchall()
            return result

    except Exception as e:
        print(f"SQL执行失败: {e}")
        return Response(json.dumps({"code": 500, "msg": "解析失败", "error": f"[SQL执行失败] {e}"}, ensure_ascii=False),
                        status=200,
                        content_type='application/json; charset=utf-8'), 200
    finally:
        connection.close()


sql_product = "SELECT DISTINCT commodity_type_detail_name  FROM spot_goods_type"
row_product = run_sql(sql_product)
sql_company = "SELECT `value`FROM configuration_instance WHERE type_code IN ('customer','supplier')"
row_company = run_sql(sql_company)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
CORS(app, resources={r"/*": {"origins": "*"}})

# 百度OCR配置
BAIDU_APP_ID = '119440941'
BAIDU_API_KEY = 'wjUtGxSglrPSWfvo66UTwPVJ'
BAIDU_SECRET_KEY = 'TK47R7PWNWhBi56V3cSBz3kocWh3I4YE'
baidu_client = AipOcr(BAIDU_APP_ID, BAIDU_API_KEY, BAIDU_SECRET_KEY)

# MinIO 配置
MINIO_ENDPOINT = "39.106.184.170:6900"
MINIO_ACCESS_KEY = "adminminio"
MINIO_SECRET_KEY = "adminminio"
BUCKET_NAME = "dev01"

# API 配置
OPENAI_API_KEY = "sk-ff33c12c69314375af461d0994e1110f"
MODEL = "qwen-vl-max"
DASHSCOPE_API_KEY = "Xg8E0Gi77hutxttimcJrJD0ccuWd7A"

# qwen-vl-max 单次最多支持的图片数量
MAX_IMAGES_PER_CALL = 10

# 初始化客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
    region="us-east-1"
)

openai_client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)


def get_content_type(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.jpg', '.jpeg']:
        return 'image/jpeg'
    elif ext == '.png':
        return 'image/png'
    elif ext == '.pdf':
        return 'application/pdf'
    elif ext in ('.doc', '.docx'):
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif ext in ('.mp3', '.wav', '.m4a', '.aac'):
        return 'audio/' + ext[1:]
    return 'application/octet-stream'


def download_file_from_url(url, temp_dir):
    """从URL下载文件到临时目录，返回文件路径和类型"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(
            url,
            stream=True,
            headers=headers,
            timeout=(10, 30),
            verify=False
        )
        response.raise_for_status()

        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if not filename:
            filename = str(uuid.uuid4())

        file_path = os.path.join(temp_dir, secure_filename(filename))

        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext == '.pdf':
            return file_path, 'pdf'
        elif file_ext in ('.jpg', '.jpeg', '.png'):
            return file_path, 'image'
        elif file_ext in ('.docx', '.doc'):
            return file_path, 'word'
        else:
            return file_path, 'unknown'

    except Exception as e:
        print(f"[下载失败] {e}")
        return None, None


def convert_pdf_to_images(pdf_path, output_dir=None, dpi=200):
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
    os.makedirs(output_dir, exist_ok=True)

    try:
        images = convert_from_path(pdf_path, dpi=dpi, fmt='jpeg')
        image_paths = []
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]

        for i, img in enumerate(images):
            img_path = os.path.join(output_dir, f"{base_name}_page_{i + 1}.jpg")
            img.save(img_path, 'JPEG', quality=95)
            image_paths.append(img_path)

        return image_paths
    except Exception as e:
        print(f"[转换失败] {e}")
        return Response(json.dumps({"code": 500, "msg": "解析失败", "error": f"[转换失败] {e}"}, ensure_ascii=False),
                        status=200,
                        content_type='application/json; charset=utf-8'), 200


def upload_to_minio(file_path):
    try:
        object_name = os.path.basename(file_path)
        content_type = get_content_type(file_path)

        minio_client.fput_object(
            bucket_name=BUCKET_NAME,
            object_name=object_name,
            file_path=file_path,
            content_type=content_type
        )

        access_url = f"https://nhzb.morningstone.cn:1443/{urllib.parse.quote(BUCKET_NAME)}/{urllib.parse.quote(object_name)}"
        return access_url
    except Exception as e:
        print(f"[上传失败] {e}")
        return Response(json.dumps({"code": 500, "msg": "解析失败", "error": f"[上传失败] {e}"}, ensure_ascii=False),
                        status=200,
                        content_type='application/json; charset=utf-8'), 200


def upload_pdf_to_dashscope(pdf_path):
    """
    将PDF文件上传到百炼 Files API，返回 file_id。
    上传后轮询等待文件解析完成（最多等60秒）。
    """
    import time

    with open(pdf_path, 'rb') as f:
        file_object = openai_client.files.create(
            file=(os.path.basename(pdf_path), f, 'application/pdf'),
            purpose="file-extract"
        )
    file_id = file_object.id
    print(f"[百炼Files] 上传成功，file_id={file_id}，等待解析...")

    max_wait = 60
    waited = 0
    while waited < max_wait:
        info = openai_client.files.retrieve(file_id=file_id)
        if getattr(info, 'status', None) in ('processed', 'available', None):
            break
        time.sleep(3)
        waited += 3

    print(f"[百炼Files] 文件就绪，file_id={file_id}")
    return file_id


def analyze_contract_pdf(file_id):
    """
    通过 fileid:// 协议将已上传的PDF传给 qwen-long 进行结构化提取。
    """
    system_content = """
你是一个专业的矿产品贸易文档分析专家。你的任务是从各类矿产品检验报告、化验报告、品质证书中提取结构化信息，并输出为标准JSON格式。

你需要处理的报告类型包括但不限于：
- CIQ品质证书/重量证书（中国海关出入境检验检疫）
- 第三方检验品质/重量证书（CCIC、SGS、Intertek、Bureau Veritas等）
- 卖方化验报告（Seller's Assay / Assay Submittal / Assay Exchange Certificate）
- 买方化验报告（Buyer's Assay）
- 仲裁化验报告（Umpire Assay / Arbitration Test Report）
- 贸易商出具的品质证书（Trader's Certificate of Analysis）
- 综合检验报告（含重量+品质的Inspection Report）

## 核心提取规则

### 1. 数据层级
报告数据存在多级嵌套结构：报告级 → 贸易级 → 批次级(Lot) → 子批次级(Sub-lot) → 混合样/汇总级(Composite)

### 2. 化学元素识别
- 铁矿计价元素: Fe (TFe)
- 铜精矿计价元素: Cu(%), Au(g/t), Ag(g/t)
- 镍铁/镍生铁计价元素: Ni(%)
- 杂质元素通常仅在Composite级别报告

### 3. 单位标准化
- 重量统一为 MT；Au/Ag 原样记录单位（g/t、g/1000kg、g/DMT 本质相同）
- 百分比只写数字，unit字段写"%"

### 4. 缺失值
所有报告中不存在的字段输出 null

### 5. 置信度
overall: high(所有数值清晰) | medium(1-3处不确定) | low(多处模糊)
"""

    user_content = r"""
请仔细阅读以上矿产品检验/化验报告，提取所有结构化信息并以JSON格式输出。

要求：
1. 完整提取所有数据，不遗漏任何Lot或元素
2. 保持原始数值精度，不进行四舍五入
3. 正确识别数据层级关系（Lot → Sub-lot → Composite）
4. 如果报告同时包含品质和重量信息，两部分都要提取
5. 对不清晰或存疑的数值，在 extraction_confidence 中标记

请按照以下JSON Schema输出：
```json
{
  "report": {
    "report_id": "报告编号",
    "report_number": "报告流水号（如有）",
    "report_date": "报告签发日期，格式YYYY-MM-DD",
    "report_type": "ciq_quality|ciq_weight|third_party_inspection|third_party_quality|third_party_weight|seller_assay|buyer_assay|assay_exchange|umpire_assay|trader_certificate|other",
    "issuing_organization": "出具机构全称",
    "issuing_organization_short": "出具机构简称",
    "inspection_standard": ["检验标准列表"],
    "analysis_methods": {"元素符号": "分析方法"}
  },
  "trade": {
    "buyer": "买方/收货人",
    "seller": "卖方/发货人",
    "contract_no": "合同号",
    "invoice_no": "发票号",
    "bl_no": "提单号",
    "client_ref": "客户参考号",
    "vessel": "船名",
    "voyage_no": "航次",
    "loadport": "装货港",
    "discharge_port": "卸货港",
    "arrival_date": "到货日期YYYY-MM-DD",
    "completion_of_discharge_date": "卸货完成日期",
    "inspection_date": "检验日期",
    "sampling_dates": "取样日期"
  },
  "cargo": {
    "commodity": "iron_ore_lump|iron_ore_fines|iron_ore_pellet|copper_concentrates|ferro_nickel|nickel_pig_iron|zinc_concentrates|lead_concentrates|other",
    "commodity_name": "商品名称原文",
    "quality_name": "品质/品牌名称",
    "declared_quantity": 数值,
    "declared_quantity_unit": "MT|KG等",
    "packing": "包装方式"
  },
  "weight": {
    "has_weight_data": 布尔值,
    "bl_weight_mt": 提单重量,
    "total_gross_weight_mt": 总毛重,
    "total_tare_weight_mt": 总皮重,
    "total_impurities_weight_mt": 总杂质重量,
    "total_moisture_weight_mt": 总水分扣减量,
    "total_wet_weight_mt": 总湿重,
    "total_dry_weight_mt": 总干重,
    "moisture_at_discharge_pct": 卸货时水分百分比,
    "moisture_deduction_mt": 总水分扣减量MT,
    "weighing_method": "称重方式",
    "scale_details": "衡器信息"
  },
  "assay": {
    "analysis_state": "dry_basis|as_received",
    "lot_data": [
      {
        "lot_id": "Lot编号",
        "gross_weight_mt": 毛重,
        "tare_weight_mt": 皮重,
        "impurities_mt": 杂质重量,
        "moisture_mt": 水分扣减量,
        "wet_weight_mt": 湿重,
        "dry_weight_mt": 干重,
        "moisture_pct": 水分百分比,
        "elements": {
          "Cu": {"value": 数值, "unit": "%"},
          "Au": {"value": 数值, "unit": "g/t"}
        },
        "sub_lots": [
          {"sub_lot_id": "子批次编号", "elements": {"Ni": {"value": 数值, "unit": "%"}}}
        ]
      }
    ],
    "composite_data": [
      {
        "composite_id": "混合样编号",
        "scope": "all_lots|P1|P2等",
        "elements": {"As": {"value": 数值, "unit": "%"}}
      }
    ],
    "weighted_average": {
      "scope": "all_lots",
      "weight_basis": "by_dmt|by_wmt|calculated",
      "elements": {"Cu": {"value": 数值, "unit": "%"}}
    }
  },
  "physical_properties": {
    "size_distribution": [
      {"fraction": "粒度描述", "value": 数值, "unit": "%", "standard": "标准号"}
    ]
  },
  "seals": {
    "seal_details": [
      {"organization": "封签机构", "seal_type": "封签类型", "status": "intact|broken"}
    ]
  },
  "extraction_confidence": {
    "overall": "high|medium|low",
    "uncertain_fields": [
      {"field_path": "JSON路径", "original_text": "原始文本", "reason": "ocr_unclear|ambiguous_layout|overlapping_text|low_resolution|conflicting_values|stamp_obstruction"}
    ]
  },
  "notes": "重要备注"
}
```

## 特别注意事项

1. **Lot编号映射**: 保留原始编号风格（纯数字、P1/P2、lot1/lot2均可）
2. **Sub-lot vs Lot**: P1-1~P1-7有P1级加权平均时，前者为sub-lots，后者为lot
3. **Composite数据**: 区分lot-level composite（如Composite P1）和overall composite/weighted average
4. **加权平均层级**: "Weighted Average P1"→填入lot_data对应Lot的elements；无Lot标识的→填入顶层weighted_average
5. **Au/Ag单位**: g/t=g/MT=g/1000kg=g/DMT，原样记录单位并在notes说明
6. **重量数据完整性**: 化验表中的DMT列不算独立称重数据（has_weight_data仍为false）
7. **缺少贸易字段正常**: 仲裁报告通常不含船名、装卸港等，缺失字段输出null
8. **稀疏数据**: 某Lot确实没有某元素值时输出null，在notes说明
9. **weight总量与lot_data明细**: 优先提取报告中的汇总值而非自行加总
"""

    messages = [
        {"role": "system", "content": system_content},
        {"role": "system", "content": f"fileid://{file_id}"},
        {"role": "user",   "content": user_content},
    ]

    try:
        completion = openai_client.chat.completions.create(
            model="qwen-long",
            messages=messages
        )
        raw = completion.choices[0].message.content.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start:end + 1])

        return {"解析失败": raw}

    except Exception as e:
        print(f"[qwen-long错误] {e}")
        return Response(
            json.dumps({"code": 500, "msg": "解析失败", "error": f"[qwen-long错误] {e}"}, ensure_ascii=False),
            status=200,
            content_type='application/json; charset=utf-8'
        )



def analyze_contract(image_urls):
    """
    image_urls: str（单张图片URL）或 list[str]（多张，对应 PDF 多页）
    将所有页图片拼入同一条 user 消息，发起单次模型调用。
    """
    if isinstance(image_urls, str):
        image_urls = [image_urls]

    # 构造多图 + 提示词的 user content
    user_content = []
    for url in image_urls:
        user_content.append({"type": "image_url", "image_url": {"url": url}})

    user_content.append({
        "type": "text",
        "text": r"""
请仔细阅读以下矿产品检验/化验报告，提取所有结构化信息并以JSON格式输出。

要求：
1. 完整提取所有数据，不遗漏任何Lot或元素
2. 保持原始数值精度，不进行四舍五入
3. 正确识别数据层级关系（Lot → Sub-lot → Composite）
4. 如果报告同时包含品质和重量信息，两部分都要提取
5. 对OCR不清晰或存疑的数值，在 extraction_confidence 中标记

请按照以下JSON Schema输出：
```json
{
  "report": {
    "report_id": "报告编号（如有多个编号，取主要编号）",
    "report_number": "报告流水号（如有）",
    "report_date": "报告签发日期，格式YYYY-MM-DD",
    "report_type": "报告类型，根据以下规则判断:
      - ciq_quality: 中国海关CIQ品质证书（标题含'品质证书'或'QUALITY CERTIFICATE'，签发机构为海关或出入境检验检疫）
      - ciq_weight: 中国海关CIQ重量证书（标题含'重量证书'或'WEIGHT CERTIFICATE'）
      - third_party_inspection: 第三方综合检验报告，同时包含重量和品质数据（如 Intertek 的 INSPECTION REPORT）
      - third_party_quality: 第三方品质/化验证书，仅含品质数据（如 CCIC 的品质证书、SGS 的 Certificate of Analysis）
      - third_party_weight: 第三方重量证书，仅含重量数据
      - seller_assay: 卖方化验报告（签发方为矿山/生产商/卖方，如 PT Freeport 的 ASSAY SUBMITTAL）
      - buyer_assay: 买方化验报告（签发方为买方或买方委托的冶炼厂）
      - assay_exchange: 品质交换意见书（买卖双方交换化验结果，标题常含 'Assay Exchange Certificate' 或 '品质交换意见'）
      - umpire_assay: 仲裁化验报告（由独立第三方仲裁实验室出具，标题含 'Umpire' 或 'Arbitration' 或 '仲裁'）
      - trader_certificate: 贸易商出具的品质证书（签发方为贸易商如 Trafigura、Glencore、IXM 等，标题常为 Certificate of Analysis）
      - other: 无法归入以上类别
      判断优先级: 先看标题/文档名称，再看签发机构身份，最后看内容结构。",
    "issuing_organization": "出具机构全称",
    "issuing_organization_short": "出具机构简称（如 CCIC, Intertek, SGS, BV, AHK, BGRIMM 等）",
    "inspection_standard": ["使用的检验标准列表，如 GB/T 6730.65-2009, ISO 3087:2020 等"],
    "analysis_methods": {
      "元素符号": "对应的分析方法或标准（如有标注）"
    }
  },

  "trade": {
    "buyer": "买方/收货人/委托方名称",
    "seller": "卖方/发货人名称（如有）",
    "contract_no": "合同号",
    "invoice_no": "发票号（如有）",
    "bl_no": "提单号（如有）",
    "client_ref": "客户参考号（如有）",
    "vessel": "船名",
    "voyage_no": "航次（如有）",
    "loadport": "装货港",
    "discharge_port": "卸货港",
    "arrival_date": "到货日期，格式YYYY-MM-DD",
    "completion_of_discharge_date": "卸货完成日期",
    "inspection_date": "检验日期（范围）",
    "sampling_dates": "取样日期（范围）"
  },

  "cargo": {
    "commodity": "商品大类，枚举值: iron_ore_lump | iron_ore_fines | iron_ore_pellet | copper_concentrates | ferro_nickel | nickel_pig_iron | zinc_concentrates | lead_concentrates | other",
    "commodity_name": "商品名称原文（如 铁矿块 IRON ORE LUMP）",
    "quality_name": "品质/品牌名称（如 Grasberg, Constancia, Red Chris, SP10F, Aranzazu 等）",
    "declared_quantity": "申报数量（数值）",
    "declared_quantity_unit": "申报数量单位（如 MT, KG）",
    "packing": "包装方式（如 In bulk, In bags）"
  },

  "weight": {
    "has_weight_data": "布尔值。报告中是否包含任何称重/重量相关数据（如过磅明细、总净重、水尺计重结果等）。仅当报告中完全没有重量信息时为 false。注意：如果重量数据仅以 lot-level 的 DMT/WMT 形式出现在化验表中（而非独立的称重章节），仍视为 has_weight_data: false，因为那些重量是化验表的辅助信息而非独立的称重结果。",
    "bl_weight_mt": "提单重量（Bill of Lading Weight），单位MT。指提单上记载的货物重量，通常为装港的湿重。在CIQ证书中常标注为'提单重量'或'B/L weight'。",
    "total_gross_weight_mt": "所有批次毛重之和（Total Gross Weight），单位MT。毛重 = 载具满载过磅的总质量，包含载具自重（皮重）、货物净重、货物水分和杂质。在报告中通常标注为 'Total Gross weight'。仅当报告提供了逐批次过磅明细（如卡车地磅称重）或汇总毛重时填写。",
    "total_tare_weight_mt": "所有批次皮重之和（Total Tare Weight），单位MT。皮重 = 空载具过磅的质量，即卡车/容器自身重量。在报告中通常标注为 'Total Tare weight'。",
    "total_impurities_weight_mt": "所有批次杂质重量之和（Total Weight of Impurities），单位MT。杂质 = 货物中混入的非目标物质（如泥土、石块、铁丝、绳索等异物），在计算净重时需扣除。在报告中通常标注为 'Total Weight of impurities'。注意：并非所有报告都有此项，主要出现在镍铁/镍生铁等散装金属的Inspection Report中。",
    "total_moisture_weight_mt": "所有批次运输水分扣减量之和（Total Weight of Moisture），单位MT。这里的水分是指运输过程中附着在货物表面的水分（非化学结合水），需在称重时扣除。注意区分：此字段是称重环节扣除的水分重量（绝对值MT），与化验环节测定的水分百分比（moisture_pct）不同。在报告中通常标注为 'Total Weight of moisture'。",
    "total_wet_weight_mt": "总湿重（Total Wet Weight），单位MT。湿重 = 毛重 - 皮重，即含水分和杂质的货物总重。部分报告直接给出此值，部分需从毛重和皮重推算。对于水尺计重（draft survey），结果通常直接为湿重。",
    "total_dry_weight_mt": "总干重/净干重（Total Dry Weight / Net Dry Weight），单位MT。干重 = 湿重 ×（1 - 水分%），即去除全部水分后的货物质量。对于地磅称重场景：净干重 = 毛重 - 皮重 - 杂质 - 运输水分。这是贸易结算最核心的重量数据。在报告中标注为 'Total Net weight of cargo'、'Total weight on dry basis' 或 'Net Dry Weight'。",
    "moisture_at_discharge_pct": "卸货时整体水分百分比（%）。通常来自CIQ重量证书中的 'Moisture of the cargo at time of discharge'。这是称重环节使用的水分值，用于从湿重推算干重。",
    "moisture_deduction_mt": "总水分扣减量（MT）。= 总湿重 × 水分百分比，或直接来自报告中标注的 'Weight of moisture that should be deducted'。",
    "weighing_method": "称重方式描述。常见值: 'draft survey'（水尺计重，通过测量船舶吃水深度推算货重）, 'bridge scale'（地磅/汽车衡，逐车过磅）, 'belt scale'（皮带秤）, 'hopper scale'（料斗秤）等。",
    "scale_details": "地磅/衡器信息（如有）。包括型号和有效期，如 'SCS-120, expiry 2026-07-08'。"
  },

  "assay": {
    "analysis_state": "分析状态，如 dry_basis | as_received",
    "lot_data": [
      {
        "lot_id": "Lot编号（如 1, 2, ... 或 P1, P2 ...）",
        "gross_weight_mt": "该批次毛重（MT）。= 满载卡车过磅的总质量之和。",
        "tare_weight_mt": "该批次皮重（MT）。= 空载卡车过磅的质量之和。",
        "impurities_mt": "该批次杂质重量（MT）。通过随机抽检卡车测定的杂质比例推算得出。",
        "moisture_mt": "该批次水分扣减量（MT）。",
        "wet_weight_mt": "该批次湿重（MT）。湿重 = 毛重 - 皮重，即含水分和杂质的货物重量。部分报告直接给出此值，部分需从毛重和皮重推算。对于水尺计重（draft survey），结果通常直接为湿重。",
        "dry_weight_mt": "该批次干重/净干重（Dry Weight / Net Dry Weight），单位MT。干重 = 湿重 ×（1 - 水分%），即去除全部水分后的货物质量。对于地磅称重场景：净干重 = 毛重 - 皮重 - 杂质 - 运输水分。这是贸易结算最核心的重量数据。",
        "moisture_pct": "该批次水分百分比（如有）",
        "elements": {
          "Cu": {"value": 21.22, "unit": "%"},
          "Au": {"value": 11.3, "unit": "g/t"},
          "Ag": {"value": 204, "unit": "g/t"},
          "Fe": {"value": null, "unit": null}
        },
        "sub_lots": [
          {
            "sub_lot_id": "子批次编号（如 P1-1, P1-2）",
            "elements": {
              "Ni": {"value": 13.75, "unit": "%"}
            }
          }
        ]
      }
    ],
    "composite_data": [
      {
        "composite_id": "混合样编号（如 Composite, Composite P1, Weighted Average 等）",
        "scope": "该composite覆盖的范围（如 all_lots | P1 | P2）",
        "elements": {
          "As": {"value": 1.88, "unit": "%"},
          "Cd": {"value": 0.009, "unit": "%"},
          "F": {"value": 349, "unit": "ppm"}
        }
      }
    ],
    "weighted_average": {
      "scope": "加权平均覆盖范围（通常为 all_lots）",
      "weight_basis": "加权基础（如 by_dmt, by_wmt, calculated）",
      "elements": {
        "Cu": {"value": 21.27, "unit": "%"},
        "Au": {"value": 11.0, "unit": "g/t"}
      }
    }
  },

  "physical_properties": {
    "size_distribution": [
      {
        "fraction": "粒度描述（如 -6.3mm, +40mm, >6.3mm）",
        "value": 8.1,
        "unit": "%",
        "standard": "ISO 4701:2019"
      }
    ]
  },

  "seals": {
    "seal_details": [
      {
        "organization": "封签机构",
        "seal_type": "封签类型（如 Company Sealing Tape, Company Stamp）",
        "status": "封签状态（如 intact, broken）"
      }
    ]
  },

  "extraction_confidence": {
    "overall": "high | medium | low",
    "uncertain_fields": [
      {
        "field_path": "JSON路径，如 assay.lot_data[2].elements.Cu.value",
        "original_text": "报告中该处的原始文本（如能识别）",
        "reason": "不确定原因，枚举: ocr_unclear | ambiguous_layout | overlapping_text | low_resolution | conflicting_values | stamp_obstruction"
      }
    ]
  },

  "notes": "报告中的重要备注、异常说明等"
}
```

## 特别注意事项

1. **Lot编号映射**: 不同报告的Lot编号风格不同。有的用纯数字（1, 2, 3），有的用前缀编号（P1, P2），有的用 lot1, lot2。保留原始编号。

2. **Sub-lot vs Lot 判断**: 如果报告中存在类似 "P1-1, P1-2, ... P1-7" 这样的编号，且有 "P1" 级别的加权平均值，则 P1-1~P1-7 是 sub-lots，P1 是 lot。

3. **Composite 数据**: 
   - 部分元素仅在 composite 样品中检测（如铜精矿的 As, F, Hg 等杂质）
   - composite 可能是全船一个（如 BCC10072S 报告），也可能每个 lot 各一个（如 Intertek 镍铁报告的 Composite P1/P2/P3）
   - 始终区分 lot-level composite（如 Composite P1）和 overall composite/weighted average

4. **加权平均值的层级区分**: 报告中可能出现两个层级的加权平均：
   - **Lot级加权平均（Per-lot Weighted Average）**: 如 "Weighted Average P1 = 13.63%"，这是该Lot下所有Sub-lot的加权平均。此值应填入 lot_data 中对应Lot的 elements 字段（即作为该Lot的代表值）。
   - **全船加权平均（Overall Weighted Average）**: 如 "Weighted Average = 14.39%"，这是所有Lot的加权平均。此值应填入顶层 weighted_average 字段。
   
   判断规则:
   - 如果加权平均值后跟有Lot标识（如 "Weighted Average P1"），则为Lot级
   - 如果加权平均值无Lot标识或标注为 "Total" / "Overall" / 仅 "Weighted Average"，则为全船级
   - 如果报告未提供加权平均值，weighted_average 输出 null，不要自行计算

5. **Au/Ag 单位**: 
   - g/t = g/MT = g/1000kg = g/DMT，本质相同
   - 部分报告用 g/t，部分用 g/1000kg，部分用 g/DMT 或 G/DMT
   - 统一记录为 "g/t"，但在 notes 中注明原始标注

6. **重量数据完整性**: 
   - CIQ重量证书和部分Inspection Report包含完整称重数据（毛重、皮重、杂质、水分、净重的逐批次明细及汇总）
   - 化验证书通常只有每个lot的DMT/WMT，这些出现在化验表中作为辅助信息，不算独立的称重数据（has_weight_data 仍为 false）
   - 卖方报告有时 DMT 标注为 "provided by client"（即非本方测定）
   - 水尺计重（draft survey）通常直接给出总湿重和水分比例，不含逐批次过磅明细

7. **报告中缺少某些贸易字段是正常的**。例如仲裁报告通常不含船名、装卸港等信息，卖方化验报告可能不含买方名称。缺失字段输出 null。

8. **多个buying/selling parties**: 仲裁报告可能同时列出买卖双方和/或两个委托方。尽量识别角色（buyer vs seller vs client）。

9. **稀疏数据（Sparse Data）**: 部分报告中，并非每个Lot都报告了所有元素。例如仲裁报告可能仅对有争议的Lot进行某元素的仲裁检测。
   - 如果某个Lot在报告中确实没有该元素的值，输出 null，不得推测或填充
   - 不要将其他Lot的值复制过来
   - 在 notes 中说明哪些元素是稀疏报告的（如 "Cu only reported for lots 1,2,11,12,13,15,18; Au reported for all lots"）

10. **weight总量与lot_data明细的关系**: 
    - weight 中的总量字段（total_gross_weight_mt 等）应与 assay.lot_data 中各批次对应字段之和一致
    - 如果报告同时给出了汇总行（如 "FINAL OUTTURN" 或 "Total"）和逐批次明细，优先提取报告中的汇总值（而非自行加总），因为可能存在尾差
    - 如果报告只给出汇总值而无逐批次明细，lot_data 中各批次的重量字段输出 null

11. **lot_data 中的重量字段来源**: lot_data 将称重数据和化验数据合并在同一个结构中。重量字段（gross_weight_mt、tare_weight_mt、impurities_mt、moisture_mt、wet_weight_mt、dry_weight_mt、moisture_pct）可能来自报告中不同章节：
    - 来自称重/过磅章节（如 Inspection Report 中的 WEIGHING 部分）：此时 gross_weight_mt、tare_weight_mt、impurities_mt、moisture_mt 通常都有值
    - 来自化验表（如铜精矿化验证书中的 DMT 列）：此时通常只有 dry_weight_mt（和/或 wet_weight_mt、moisture_pct），其余称重字段为 null
    - 提取时从报告中各自对应位置取值，所有在报告中未出现的重量字段输出 null

---

## 附录：各报告类型的字段覆盖矩阵

下表标注了每种报告类型通常包含（✓）或不包含（✗）的字段，帮助校验提取结果的完整性。

| 字段 | CIQ品质 | CIQ重量 | 第三方品质 | 第三方检验 | 卖方化验 | 买方化验 | 仲裁化验 | 贸易商证书 | 品质交换 |
|------|---------|---------|----------|----------|----------|----------|----------|----------|----------|
| report_id | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| contract_no | ✓ | ✓ | ✓ | ✓ | 有时 | 有时 | 有时 | 有时 | ✓ |
| vessel | ✓ | ✓ | ✓ | 有时 | ✓ | 有时 | 有时 | ✓ | 有时 |
| loadport | ✓ | ✓ | 有时 | 有时 | ✓ | ✗ | ✗ | 有时 | 有时 |
| discharge_port | ✓ | ✓ | 有时 | ✓ | ✓ | ✓ | ✗ | 有时 | ✓ |
| bl_weight | ✓ | ✓ | ✓ | 有时 | ✗ | ✗ | ✗ | ✗ | ✗ |
| 过磅明细(gross/tare/net) | ✗ | ✓(汇总) | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| lot_assay | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| sub_lot_assay | ✗ | ✗ | ✗ | 有时(镍铁) | ✗ | ✗ | ✗ | ✗ | ✗ |
| composite_data | ✗ | ✗ | 有时 | ✓ | 有时 | 有时 | ✗ | 有时 | ✗ |
| weighted_average | ✓(隐含) | ✗ | 有时 | ✓ | ✓ | ✓ | ✗ | 有时 | ✓ |
| seals | ✗ | ✗ | ✓ | 有时 | ✗ | ✗ | ✓ | ✗ | ✗ |
| size_distribution | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

---

## 附录：实际报告提取示例

### 示例1: Intertek LSI Report (BCC10072S) — 铜精矿第三方品质证书

```json
{
  "report": {
    "report_id": "BCC10072S",
    "report_number": "LSI 6846 - 58999",
    "report_date": "2022-01-25",
    "report_type": "certificate_of_analysis",
    "issuing_organization": "Laboratory Services International Rotterdam BV (Intertek)",
    "issuing_organization_short": "Intertek LSI",
    "inspection_standard": ["NEN-EN-ISO/IEC 17025"],
    "analysis_methods": {
      "Cu": "W0700 - Volumetric - In House Method",
      "Ag": "W0703 - AAS - In House Method",
      "Au": "W0701 - Fire Assay Gravimetric - In House Method"
    }
  },
  "trade": {
    "buyer": "IXM S.A.",
    "seller": null,
    "contract_no": null,
    "invoice_no": null,
    "bl_no": null,
    "client_ref": "BCC10072S",
    "vessel": "APL ESPLANADE",
    "voyage_no": null,
    "loadport": null,
    "discharge_port": null,
    "arrival_date": null,
    "completion_of_discharge_date": null,
    "inspection_date": null,
    "sampling_dates": null
  },
  "cargo": {
    "commodity": "copper_concentrates",
    "commodity_name": "ARANZAZU COPPER CONCENTRATES",
    "quality_name": "Aranzazu",
    "declared_quantity": 224.995,
    "declared_quantity_unit": "DMT",
    "packing": null
  },
  "weight": {
    "has_weight_data": false,
    "bl_weight_mt": null,
    "total_gross_weight_mt": null,
    "total_tare_weight_mt": null,
    "total_impurities_weight_mt": null,
    "total_moisture_weight_mt": null,
    "total_wet_weight_mt": null,
    "total_dry_weight_mt": null,
    "moisture_at_discharge_pct": null,
    "moisture_deduction_mt": null,
    "weighing_method": null,
    "scale_details": null
  },
  "assay": {
    "analysis_state": "dry_basis",
    "lot_data": [
      {"lot_id": "1", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 404.907, "moisture_pct": null, "elements": {"Cu": {"value": 21.22, "unit": "%"}, "Ag": {"value": 204, "unit": "g/t"}, "Au": {"value": 11.3, "unit": "g/t"}}, "sub_lots": []},
      {"lot_id": "2", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 401.427, "moisture_pct": null, "elements": {"Cu": {"value": 21.31, "unit": "%"}, "Ag": {"value": 204, "unit": "g/t"}, "Au": {"value": 10.7, "unit": "g/t"}}, "sub_lots": []},
      {"lot_id": "3", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 408.911, "moisture_pct": null, "elements": {"Cu": {"value": 21.27, "unit": "%"}, "Ag": {"value": 205, "unit": "g/t"}, "Au": {"value": 11.4, "unit": "g/t"}}, "sub_lots": []},
      {"lot_id": "4", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 404.646, "moisture_pct": null, "elements": {"Cu": {"value": 21.28, "unit": "%"}, "Ag": {"value": 207, "unit": "g/t"}, "Au": {"value": 11.4, "unit": "g/t"}}, "sub_lots": []},
      {"lot_id": "5", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 405.104, "moisture_pct": null, "elements": {"Cu": {"value": 21.28, "unit": "%"}, "Ag": {"value": 203, "unit": "g/t"}, "Au": {"value": 12.0, "unit": "g/t"}}, "sub_lots": []}
    ],
    "composite_data": [
      {
        "composite_id": "Composite",
        "scope": "all_lots",
        "elements": {
          "As": {"value": 1.88, "unit": "%"},
          "Cd": {"value": 0.009, "unit": "%"},
          "Zn+Pb": {"value": 1.19, "unit": "%"},
          "Bi": {"value": 0.19, "unit": "%"},
          "Sb": {"value": 0.12, "unit": "%"},
          "Hg": {"value": 1, "unit": "ppm"},
          "F": {"value": 349, "unit": "ppm"},
          "Al2O3+MgO": {"value": 1.77, "unit": "%"}
        }
      }
    ],
    "weighted_average": null
  },
  "physical_properties": {"size_distribution": []},
  "seals": {
    "seal_details": [
      {"organization": "CCICGX", "seal_type": "Company Sealing Tape", "status": "intact"},
      {"organization": "Intertek", "seal_type": "Company Stamp", "status": "intact"},
      {"organization": "C.C.I.C. Guangxi Co., Ltd.", "seal_type": "Company Stamp", "status": "intact"}
    ]
  },
  "extraction_confidence": {
    "overall": "high",
    "uncertain_fields": []
  },
  "notes": "DMT values provided by client. Hg tested on sample as received (not dry basis). Original Au/Ag unit in report: g/t."
}
```

### 示例2: Intertek Inspection Report (RMIN2600595) — 镍铁综合检验报告（含Sub-lot和完整称重明细）

```json
{
  "report": {
    "report_id": "MIN260100148NC",
    "report_number": "RMIN2600595",
    "report_date": "2026-02-03",
    "report_type": "third_party_inspection",
    "issuing_organization": "Intertek Testing Services Ltd., Shanghai",
    "issuing_organization_short": "Intertek",
    "inspection_standard": ["YS/T 953.1-2014", "YS/T 953.9-2014", "GB/T 32794-2016", "A/ICP-OES02:2017"],
    "analysis_methods": {
      "Ni": "YS/T 953.1-2014",
      "Si": "A/ICP-OES02:2017",
      "C": "YS/T 953.9-2014",
      "S": "YS/T 953.9-2014",
      "P": "GB/T 32794-2016",
      "Cr": "GB/T 32794-2016"
    }
  },
  "trade": {
    "buyer": "五矿有色金属股份有限公司 & 山东太钢鑫海不锈钢有限公司",
    "seller": null,
    "contract_no": null,
    "invoice_no": null,
    "bl_no": null,
    "client_ref": "26CNMIS7202TGXH01F",
    "vessel": null,
    "voyage_no": null,
    "loadport": null,
    "discharge_port": null,
    "arrival_date": null,
    "completion_of_discharge_date": null,
    "inspection_date": "2026-01-16 to 2026-01-18",
    "sampling_dates": "2026-01-16 to 2026-01-18"
  },
  "cargo": {
    "commodity": "ferro_nickel",
    "commodity_name": "Ferro Nickel",
    "quality_name": null,
    "declared_quantity": 3000,
    "declared_quantity_unit": "MT",
    "packing": "In bulk"
  },
  "weight": {
    "has_weight_data": true,
    "bl_weight_mt": null,
    "total_gross_weight_mt": 4599.340,
    "total_tare_weight_mt": 1718.980,
    "total_impurities_weight_mt": 19.076,
    "total_moisture_weight_mt": 5.973,
    "total_wet_weight_mt": null,
    "total_dry_weight_mt": 2855.311,
    "moisture_at_discharge_pct": null,
    "moisture_deduction_mt": null,
    "weighing_method": "bridge scale, trucks weighed laden and empty, deducted impurities and moisture",
    "scale_details": "SCS-120, expiry 2026-07-08"
  },
  "assay": {
    "analysis_state": "dry_basis",
    "lot_data": [
      {
        "lot_id": "P1",
        "gross_weight_mt": 1356.920,
        "tare_weight_mt": 507.280,
        "impurities_mt": 7.630,
        "moisture_mt": 2.358,
        "wet_weight_mt": null,
        "dry_weight_mt": 839.652,
        "moisture_pct": null,
        "elements": {
          "Ni": {"value": 13.63, "unit": "%"}
        },
        "sub_lots": [
          {"sub_lot_id": "P1-1", "elements": {"Ni": {"value": 13.75, "unit": "%"}}},
          {"sub_lot_id": "P1-2", "elements": {"Ni": {"value": 13.66, "unit": "%"}}},
          {"sub_lot_id": "P1-3", "elements": {"Ni": {"value": 13.50, "unit": "%"}}},
          {"sub_lot_id": "P1-4", "elements": {"Ni": {"value": 13.62, "unit": "%"}}},
          {"sub_lot_id": "P1-5", "elements": {"Ni": {"value": 13.59, "unit": "%"}}},
          {"sub_lot_id": "P1-6", "elements": {"Ni": {"value": 13.62, "unit": "%"}}},
          {"sub_lot_id": "P1-7", "elements": {"Ni": {"value": 13.64, "unit": "%"}}}
        ]
      },
      {
        "lot_id": "P2",
        "gross_weight_mt": 2610.180,
        "tare_weight_mt": 975.900,
        "impurities_mt": 9.266,
        "moisture_mt": 2.275,
        "wet_weight_mt": null,
        "dry_weight_mt": 1622.739,
        "moisture_pct": null,
        "elements": {
          "Ni": {"value": 14.37, "unit": "%"}
        },
        "sub_lots": [
          {"sub_lot_id": "P2-1", "elements": {"Ni": {"value": 14.31, "unit": "%"}}},
          {"sub_lot_id": "P2-2", "elements": {"Ni": {"value": 14.41, "unit": "%"}}},
          {"sub_lot_id": "P2-3", "elements": {"Ni": {"value": 14.43, "unit": "%"}}},
          {"sub_lot_id": "P2-4", "elements": {"Ni": {"value": 14.38, "unit": "%"}}},
          {"sub_lot_id": "P2-5", "elements": {"Ni": {"value": 14.37, "unit": "%"}}},
          {"sub_lot_id": "P2-6", "elements": {"Ni": {"value": 14.15, "unit": "%"}}},
          {"sub_lot_id": "P2-7", "elements": {"Ni": {"value": 14.53, "unit": "%"}}},
          {"sub_lot_id": "P2-8", "elements": {"Ni": {"value": 14.33, "unit": "%"}}},
          {"sub_lot_id": "P2-9", "elements": {"Ni": {"value": 14.38, "unit": "%"}}},
          {"sub_lot_id": "P2-10", "elements": {"Ni": {"value": 14.39, "unit": "%"}}},
          {"sub_lot_id": "P2-11", "elements": {"Ni": {"value": 14.41, "unit": "%"}}}
        ]
      },
      {
        "lot_id": "P3",
        "gross_weight_mt": 632.240,
        "tare_weight_mt": 235.800,
        "impurities_mt": 2.180,
        "moisture_mt": 1.340,
        "wet_weight_mt": null,
        "dry_weight_mt": 392.920,
        "moisture_pct": null,
        "elements": {
          "Ni": {"value": 16.12, "unit": "%"}
        },
        "sub_lots": [
          {"sub_lot_id": "P3-1", "elements": {"Ni": {"value": 16.15, "unit": "%"}}},
          {"sub_lot_id": "P3-2", "elements": {"Ni": {"value": 16.08, "unit": "%"}}},
          {"sub_lot_id": "P3-3", "elements": {"Ni": {"value": 16.13, "unit": "%"}}}
        ]
      }
    ],
    "composite_data": [
      {
        "composite_id": "Composite P1",
        "scope": "P1",
        "elements": {
          "Si": {"value": 0.037, "unit": "%"},
          "C": {"value": 2.34, "unit": "%"},
          "S": {"value": 0.282, "unit": "%"},
          "P": {"value": 0.026, "unit": "%"},
          "Cr": {"value": 0.28, "unit": "%"}
        }
      },
      {
        "composite_id": "Composite P2",
        "scope": "P2",
        "elements": {
          "Si": {"value": 0.031, "unit": "%"},
          "C": {"value": 2.33, "unit": "%"},
          "S": {"value": 0.255, "unit": "%"},
          "P": {"value": 0.026, "unit": "%"},
          "Cr": {"value": 0.26, "unit": "%"}
        }
      },
      {
        "composite_id": "Composite P3",
        "scope": "P3",
        "elements": {
          "Si": {"value": 0.037, "unit": "%"},
          "C": {"value": 2.10, "unit": "%"},
          "S": {"value": 0.270, "unit": "%"},
          "P": {"value": 0.037, "unit": "%"},
          "Cr": {"value": 0.23, "unit": "%"}
        }
      }
    ],
    "weighted_average": {
      "scope": "all_lots",
      "weight_basis": "calculated",
      "elements": {
        "Ni": {"value": 14.39, "unit": "%"},
        "Si": {"value": 0.034, "unit": "%"},
        "C": {"value": 2.30, "unit": "%"},
        "S": {"value": 0.265, "unit": "%"},
        "P": {"value": 0.028, "unit": "%"},
        "Cr": {"value": 0.26, "unit": "%"}
      }
    }
  },
  "physical_properties": {"size_distribution": []},
  "seals": {"seal_details": []},
  "extraction_confidence": {
    "overall": "high",
    "uncertain_fields": []
  },
  "notes": "Impurity result from random truck checking is referential only. Place of inspection: Shandong, China. Lot-level Ni values (e.g. P1=13.63%) are per-lot weighted averages of their sub-lots, as labeled 'Weighted Average P1' in the report."
}
```

### 示例3: Bureau Veritas Umpire (UKWTMJ22006852) — 铜精矿仲裁（稀疏数据）

```json
{
  "report": {
    "report_id": "UKWTMJ22006852/1-1",
    "report_number": null,
    "report_date": "2022-10-10",
    "report_type": "umpire_assay",
    "issuing_organization": "Bureau Veritas Commodities UK Limited",
    "issuing_organization_short": "BV",
    "inspection_standard": ["EN ISO/IEC 17025:2017"],
    "analysis_methods": {
      "Cu": "G90",
      "Au": "F25"
    }
  },
  "trade": {
    "buyer": "China Minmetals Non-ferrous Metals Co.,Ltd.",
    "seller": "Newcrest Red Chris Mining Limited",
    "contract_no": null,
    "invoice_no": null,
    "bl_no": null,
    "client_ref": "RC-104Z",
    "vessel": "SAGA TUCANO",
    "voyage_no": null,
    "loadport": null,
    "discharge_port": null,
    "arrival_date": null,
    "completion_of_discharge_date": null,
    "inspection_date": null,
    "sampling_dates": null
  },
  "cargo": {
    "commodity": "copper_concentrates",
    "commodity_name": "Red Chris Copper Concentrate",
    "quality_name": "Red Chris",
    "declared_quantity": null,
    "declared_quantity_unit": null,
    "packing": null
  },
  "weight": {
    "has_weight_data": false,
    "bl_weight_mt": null,
    "total_gross_weight_mt": null,
    "total_tare_weight_mt": null,
    "total_impurities_weight_mt": null,
    "total_moisture_weight_mt": null,
    "total_wet_weight_mt": null,
    "total_dry_weight_mt": null,
    "moisture_at_discharge_pct": null,
    "moisture_deduction_mt": null,
    "weighing_method": null,
    "scale_details": null
  },
  "assay": {
    "analysis_state": "dry_basis",
    "lot_data": [
      {"lot_id": "1", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 452.409, "moisture_pct": null, "elements": {"Cu": {"value": 22.65, "unit": "%"}, "Au": {"value": 14.8, "unit": "g/t"}}, "sub_lots": []},
      {"lot_id": "2", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 455.239, "moisture_pct": null, "elements": {"Cu": {"value": 22.99, "unit": "%"}, "Au": {"value": null, "unit": null}}, "sub_lots": []},
      {"lot_id": "4", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 452.909, "moisture_pct": null, "elements": {"Cu": {"value": null, "unit": null}, "Au": {"value": 14.4, "unit": "g/t"}}, "sub_lots": []},
      {"lot_id": "6", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 457.916, "moisture_pct": null, "elements": {"Cu": {"value": null, "unit": null}, "Au": {"value": 15.1, "unit": "g/t"}}, "sub_lots": []},
      {"lot_id": "7", "gross_weight_mt": null, "tare_weight_mt": null, "impurities_mt": null, "moisture_mt": null, "wet_weight_mt": null, "dry_weight_mt": 447.111, "moisture_pct": null, "elements": {"Cu": {"value": null, "unit": null}, "Au": {"value": 15.3, "unit": "g/t"}}, "sub_lots": []}
    ],
    "composite_data": [],
    "weighted_average": null
  },
  "physical_properties": {"size_distribution": []},
  "seals": {
    "seal_details": [
      {"organization": "CCIC CCICGX", "seal_type": null, "status": null},
      {"organization": "A.H. Knight (Jinling) Co LTD", "seal_type": null, "status": null},
      {"organization": "China Certification and Inspection", "seal_type": null, "status": null}
    ]
  },
  "extraction_confidence": {
    "overall": "high",
    "uncertain_fields": []
  },
  "notes": "Sparse data: Cu only reported for lots 1,2,11,12,13,15,18; Au reported for all lots. Lot numbering is non-sequential (lots 3,5,14 are missing from this report). Weight refers to net dry weight. Original Au unit in report: g/1000kg."
}
```
"""
    })

    messages = [
        {
            "role": "system",
            "content": f"""
你是一个专业的矿产品贸易文档分析专家。你的任务是从各类矿产品检验报告、化验报告、品质证书中提取结构化信息，并输出为标准JSON格式。

你需要处理的报告类型包括但不限于：
- CIQ品质证书/重量证书（中国海关出入境检验检疫）
- 第三方检验品质/重量证书（CCIC、SGS、Intertek、Bureau Veritas等）
- 卖方化验报告（Seller's Assay / Assay Submittal / Assay Exchange Certificate）
- 买方化验报告（Buyer's Assay）
- 仲裁化验报告（Umpire Assay / Arbitration Test Report）
- 贸易商出具的品质证书（Trader's Certificate of Analysis）
- 综合检验报告（含重量+品质的Inspection Report）

你需要处理的商品类型包括但不限于：
- 铁矿石（块矿Iron Ore Lump / 粉矿Iron Ore Fines / 球团Pellet）
- 铜精矿（Copper Concentrates）
- 镍铁（Ferro Nickel）
- 镍生铁（Nickel Pig Iron / NPI）
- 锌精矿（Zinc Concentrates）
- 铅精矿（Lead Concentrates）
- 其他矿产品

## 核心提取规则

### 1. 数据层级
报告数据存在多级嵌套结构，你必须完整识别：
- **报告级 (Report Level)**: 报告元信息
- **贸易级 (Trade Level)**: 买卖双方、合同、船舶等
- **批次级 (Lot Level)**: 每个Lot的重量和计价元素含量
- **子批次级 (Sub-lot Level)**: 部分报告中Lot下还有Sub-lot（如镍铁报告中P1下有P1-1~P1-7）
- **混合样/汇总级 (Composite/Summary Level)**: 杂质元素通常只在此级别报告

### 2. 化学元素识别
根据商品类型，自动识别并归类：

**计价元素（Payable Elements）**— 通常逐Lot报告：
- 铁矿: Fe (TFe全铁)
- 铜精矿: Cu (%), Au (g/t 或 g/MT 或 g/1000kg), Ag (g/t 或 g/MT)
- 镍铁 (Ferro Nickel): Ni (%)
- 镍生铁 (Nickel Pig Iron / NPI): Ni (%)
  注意区分: Ferro Nickel 通常指印尼/新喀等产的铸锭，Nickel Pig Iron (镍生铁) 通常指中国/印尼产的低品位含镍铁合金。
  判断依据: 报告中的commodity名称原文。如写 "Ferro Nickel" 则为 ferro_nickel，如写 "Nickel Pig Iron" 或 "镍生铁" 则为 nickel_pig_iron。

**杂质/罚款元素（Penalty Elements）**— 通常仅在Composite级别报告：
- 铁矿: SiO₂, Al₂O₃, S, P
- 铜精矿: As, Cd, Zn+Pb, Bi, Sb, Hg, F, Al₂O₃+MgO
- 镍铁/镍生铁: Si, C, S, P, Cr

**物理指标**：
- 水分 (Moisture %)
- 粒度 (Size distribution)

### 3. 单位标准化
- 重量: 统一转为 MT (Metric Ton)，保留原始精度
- Au/Ag 含量: 注意区分 g/t、g/MT、g/1000kg、g/DMT（本质相同但标注不同），原样记录单位
- 百分比含量: 记录为数字（不含%符号），在unit字段注明"%"
- ppm 含量: 保留原始单位

### 4. 缺失值处理
- 某个字段在报告中不存在: 输出 null
- 某个Lot的某个元素值被省略（如仅部分Lot报告了Cu）: 该Lot该元素输出 null
- 报告中用 "/" 或 "-" 或空白表示未检测: 输出 null

### 5. 置信度与OCR不确定性
部分报告为扫描件，可能存在OCR识别困难。遇到以下情况时，必须在 extraction_confidence.uncertain_fields 中标记：
- 数字模糊或可能被误读（如 "1" vs "7"，"6" vs "8"，"0.03" vs "0.08"）
- 表格对齐不清，无法确定某个数值属于哪一列/哪一行
- 文字被印章、水印、背景花纹遮挡
- 同一元素在报告不同位置出现矛盾数值

overall 置信度判断标准：
- high: 报告为电子版或高清扫描，所有数值清晰可读
- medium: 大部分清晰，但有1-3处不确定
- low: 多处模糊或布局难以解析
"""
        },
        {
            "role": "user",
            "content": user_content
        }
    ]

    try:
        completion = openai_client.chat.completions.create(
            model=MODEL,
            messages=messages
        )
        raw = completion.choices[0].message.content.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start:end + 1])

        return {"解析失败": raw}

    except Exception as e:
        print(f"[OpenAI错误] {e}")
        return Response(
            json.dumps({"code": 500, "msg": "解析失败", "error": f"[OpenAI错误] {e}"}, ensure_ascii=False),
            status=200,
            content_type='application/json; charset=utf-8'
        )


def mark_extracted_values(image_path, extracted_data, output_dir=None):
    """
    在图片上标注提取出的合同关键信息
    """
    if not image_path.lower().endswith(('.jpg', '.jpeg', '.png')):
        return Response(
            json.dumps({
                "code": 400,
                "msg": "只能处理图片文件",
                "error": f"文件 {image_path} 不是支持的图片格式"
            }, ensure_ascii=False),
            status=400,
            content_type='application/json; charset=utf-8'
        )

    original_name = os.path.basename(image_path)
    if output_dir is None:
        output_dir = os.path.dirname(image_path)

    marked_name = f"marked_{uuid.uuid4().hex[:8]}_{original_name}"
    output_path = os.path.join(output_dir, marked_name)

    os.makedirs(output_dir, exist_ok=True)

    try:
        target_fields = {}
        contract_info = extracted_data.get("合同基础信息", {})

        for field_name, value in contract_info.items():
            if value and str(value).strip():
                target_fields[str(value)] = field_name

        remarks = extracted_data.get("备注", "")
        if remarks and str(remarks).strip():
            target_fields[str(remarks)] = "备注"

        if not target_fields:
            print("没有找到可标注的值")
            return Response(
                json.dumps({
                    "code": 500,
                    "msg": "解析失败",
                    "error": "没有找到可标注的值"
                }, ensure_ascii=False),
                status=500,
                content_type='application/json; charset=utf-8'
            )

        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("simsun.ttc", 20)
        except:
            try:
                font = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc", 20)
            except:
                font = ImageFont.load_default()

        with open(image_path, 'rb') as f:
            image_data = f.read()

        result = baidu_client.general(image_data)
        found_values = {}

        if 'words_result' in result:
            for item in result['words_result']:
                for text_value, field_name in target_fields.items():
                    if text_value in item['words'] and 'location' in item:
                        location = item['location']
                        x, y, w, h = location['left'], location['top'], location['width'], location['height']

                        draw.rectangle([x, y, x + w, y + h], outline="red", width=2)
                        draw.text((x, y + h + 5), field_name, fill="blue", font=font)

                        found_values[field_name] = {
                            "value": text_value,
                            "location": location
                        }

        img.save(output_path)
        print(f"标注图片已保存到: {output_path}")
        return output_path, found_values

    except Exception as e:
        print(f"图片标注失败: {str(e)}")
        return Response(
            json.dumps({
                "code": 500,
                "msg": "解析失败",
                "error": f"[图片标注失败] {str(e)}"
            }, ensure_ascii=False),
            status=500,
            content_type='application/json; charset=utf-8'
        )


def add_prefix_to_filename(filepath, prefix="marked_"):
    directory, filename = os.path.split(filepath)
    new_filename = prefix + filename
    new_filepath = os.path.join(directory, new_filename)
    return new_filepath


def merge_results(page_results):
    """合并多页分析结果"""
    if not page_results:
        return {}

    merged = {
        '合同基础信息': []
    }

    for result in page_results:
        for i in result:
            merged['合同基础信息'].append(i)
    return merged


def docx_to_pdf(docx_path):
    """使用LibreOffice将docx转换为PDF"""
    if not os.path.exists(docx_path):
        raise FileNotFoundError(f"文件 {docx_path} 不存在")

    pdf_path = os.path.splitext(docx_path)[0] + ".pdf"
    libreoffice_path = r"C:\Program Files\LibreOffice\program\soffice.exe"

    try:
        subprocess.run([
            libreoffice_path,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            os.path.dirname(docx_path) or ".",
            docx_path
        ], check=True)
        return pdf_path

    except subprocess.CalledProcessError as e:
        raise Exception(f"转换失败: {e}")

def process_single_file(file_path, file_type, temp_dir):
    """处理单个文件"""
    file_result = {
        "filename": os.path.basename(file_path),
        "fileId": str(uuid.uuid4()),
        "merged_data": None,
        "pages": []
    }

    # ── PDF 处理 ──────────────────────────────────────────────
    if file_type == 'pdf':
        images = convert_pdf_to_images(file_path, temp_dir)
        if not images:
            return []

        # ① 所有页先上传到 MinIO，收集 URL
        all_img_urls = []
        for img_path in images:
            img_url = upload_to_minio(img_path)
            if isinstance(img_url, Response):   # 上传失败时 upload_to_minio 返回 Response
                return img_url
            if img_url:
                all_img_urls.append(img_url)

        if not all_img_urls:
            return []

        # ② 按 MAX_IMAGES_PER_CALL 分批，每批单次调用模型
        batch_results = []
        for batch_start in range(0, len(all_img_urls), MAX_IMAGES_PER_CALL):
            batch_urls = all_img_urls[batch_start: batch_start + MAX_IMAGES_PER_CALL]
            print(f"[PDF] 调用模型，第 {batch_start // MAX_IMAGES_PER_CALL + 1} 批，共 {len(batch_urls)} 页")

            extracted_data = analyze_contract(batch_urls)
            if isinstance(extracted_data, Response):
                return extracted_data
            if "解析失败" not in extracted_data:
                batch_results.append(extracted_data)

        # ③ 合并各批结果
        if batch_results:
            file_result["merged_data"] = (
                merge_results(batch_results) if len(batch_results) > 1 else batch_results[0]
            )

        return [file_result]

    # ── Word 处理 ─────────────────────────────────────────────
    elif file_type == 'word':
        try:
            pdf_path = docx_to_pdf(file_path)
            images = convert_pdf_to_images(pdf_path, temp_dir)
            if not images:
                return []

            page_results = []
            for i, img_path in enumerate(images):
                img_url = upload_to_minio(img_path)
                if not img_url:
                    continue

                extracted_data = analyze_contract(img_url)
                if isinstance(extracted_data, Response):
                    return extracted_data
                if "解析失败" in extracted_data:
                    continue

                marked_result = mark_extracted_values(
                    img_path,
                    extracted_data,
                    os.path.join(temp_dir, "marked_images")
                )
                if isinstance(marked_result, Response):
                    return marked_result
                else:
                    marked_img_path, found_values = marked_result
                    if marked_img_path:
                        marked_img_url = upload_to_minio(marked_img_path)
                        if marked_img_url:
                            page_results.append(extracted_data)
                            file_result["pages"].append({
                                "original_image_url": img_url,
                                "marked_image_url": marked_img_url,
                                "found_values": found_values,
                                "page_number": i + 1
                            })

            if page_results:
                file_result["merged_data"] = merge_results(page_results) if len(page_results) > 1 else page_results[0]

        except Exception as e:
            print(f"Word文件处理失败: {e}")
            return Response(
                json.dumps({"code": 500, "msg": "解析失败", "error": f"[Word文件处理失败] {e}"}, ensure_ascii=False),
                status=200,
                content_type='application/json; charset=utf-8'
            )

        return [file_result]

    # ── 图片处理 ──────────────────────────────────────────────
    elif file_type == 'image':
        img_url = upload_to_minio(file_path)
        if img_url:
            extracted_data = analyze_contract(img_url)
            if isinstance(extracted_data, Response):
                return extracted_data
            if "解析失败" not in extracted_data:
                marked_result = mark_extracted_values(
                    file_path,
                    extracted_data,
                    os.path.join(temp_dir, "marked_images")
                )
                if isinstance(marked_result, Response):
                    return marked_result
                else:
                    marked_img_path, found_values = marked_result
                    if marked_img_path:
                        marked_img_url = upload_to_minio(marked_img_path)
                        if marked_img_url:
                            file_result["pages"].append({
                                "original_image_url": img_url,
                                "marked_image_url": marked_img_url,
                                "found_values": found_values,
                                "page_number": 1
                            })
                            file_result["merged_data"] = extracted_data

        return [file_result]


@app.route('/api/analyze-contract', methods=['POST'])
def extract_and_mark_api():
    data = request.get_json()
    if not data or 'urls' not in data:
        return Response(json.dumps({"code": 400, "msg": "No URLs provided"}, ensure_ascii=False),
                        content_type='application/json; charset=utf-8'), 400

    urls = data['urls']
    if not isinstance(urls, list) or len(urls) == 0:
        return Response(json.dumps({"code": 400, "msg": "Invalid URLs format"}, ensure_ascii=False),
                        content_type='application/json; charset=utf-8'), 400

    try:
        temp_dir = tempfile.mkdtemp()
        all_results = []

        for url in urls:
            try:
                file_path, file_type = download_file_from_url(url, temp_dir)
                if not file_path:
                    continue

                file_results = process_single_file(file_path, file_type, temp_dir)
                if isinstance(file_results, Response):
                    return file_results

                for result in file_results:
                    result["fileurl"] = url
                all_results.extend(file_results)

            except Exception as e:
                print(f"处理URL {url} 时出错: {e}")
                continue

        shutil.rmtree(temp_dir, ignore_errors=True)

        return Response(
            json.dumps({
                "code": 200,
                "msg": "处理成功",
                "results": all_results,
                "total_urls": len(urls),
                "processed_urls": len(all_results)
            }, ensure_ascii=False, indent=2),
            status=200,
            content_type='application/json; charset=utf-8'
        )

    except Exception as e:
        print(f"[处理失败] {e}")
        return Response(
            json.dumps({"code": 500, "msg": "解析失败", "error": f"[处理失败] {e}"}, ensure_ascii=False),
            status=200,
            content_type='application/json; charset=utf-8'
        ), 200


@app.route('/api/analyze-contract-upload', methods=['POST'])
def analyze_contract_upload_api():
    """
    接受 multipart/form-data 文件上传。
    字段名: files（支持多个文件）
    - PDF  → 直接上传到百炼 Files API，用 qwen-long + fileid:// 解析
    - 图片 → 上传到 MinIO，用 qwen-vl-max 解析
    - Word → 先转PDF，再走 PDF 分支
    """
    if 'files' not in request.files:
        return Response(
            json.dumps({"code": 400, "msg": "No files provided"}, ensure_ascii=False),
            content_type='application/json; charset=utf-8'
        ), 400

    uploaded_files = request.files.getlist('files')
    if not uploaded_files:
        return Response(
            json.dumps({"code": 400, "msg": "Empty files list"}, ensure_ascii=False),
            content_type='application/json; charset=utf-8'
        ), 400

    temp_dir = tempfile.mkdtemp()
    all_results = []

    try:
        for upload in uploaded_files:
            filename = secure_filename(upload.filename)
            if not filename:
                continue

            file_path = os.path.join(temp_dir, filename)
            upload.save(file_path)

            ext = os.path.splitext(filename)[1].lower()
            file_result = {
                "filename": filename,
                "fileId": str(uuid.uuid4()),
                "merged_data": None,
                "pages": []
            }

            try:
                if ext == '.pdf':
                    # PDF → 百炼 Files API → qwen-long
                    fid = upload_pdf_to_dashscope(file_path)
                    extracted_data = analyze_contract_pdf(fid)
                    if isinstance(extracted_data, Response):
                        return extracted_data
                    if "解析失败" not in extracted_data:
                        file_result["merged_data"] = extracted_data
                    all_results.append(file_result)

                elif ext in ('.jpg', '.jpeg', '.png'):
                    # 图片 → MinIO → qwen-vl-max
                    img_url = upload_to_minio(file_path)
                    if isinstance(img_url, Response):
                        return img_url
                    if img_url:
                        extracted_data = analyze_contract(img_url)
                        if isinstance(extracted_data, Response):
                            return extracted_data
                        if "解析失败" not in extracted_data:
                            file_result["merged_data"] = extracted_data
                            file_result["pages"].append({
                                "original_image_url": img_url,
                                "page_number": 1
                            })
                    all_results.append(file_result)

                elif ext in ('.doc', '.docx'):
                    # Word → PDF → 百炼 Files API → qwen-long
                    pdf_path_converted = docx_to_pdf(file_path)
                    fid = upload_pdf_to_dashscope(pdf_path_converted)
                    extracted_data = analyze_contract_pdf(fid)
                    if isinstance(extracted_data, Response):
                        return extracted_data
                    if "解析失败" not in extracted_data:
                        file_result["merged_data"] = extracted_data
                    all_results.append(file_result)

                else:
                    print(f"[跳过] 不支持的文件类型: {filename}")

            except Exception as e:
                print(f"处理文件 {filename} 时出错: {e}")
                continue

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return Response(
        json.dumps({
            "code": 200,
            "msg": "处理成功",
            "results": all_results,
            "total_files": len(uploaded_files),
            "processed_files": len(all_results)
        }, ensure_ascii=False, indent=2),
        status=200,
        content_type='application/json; charset=utf-8'
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8012, debug=True)