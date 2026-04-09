{
  "report": {
    "report_id": "报告编号（如有多个编号，取主要编号）",
    "report_number": "报告流水号（如有）",
    "report_date": "报告签发日期，格式YYYY-MM-DD",
    "report_type": "报告类型，枚举值: ciq_quality | ciq_weight | third_party_quality | third_party_weight | third_party_inspection | seller_assay | buyer_assay | umpire_assay | arbitration | assay_exchange | certificate_of_analysis | other",
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
    "commodity": "商品大类，枚举值: iron_ore_lump | iron_ore_fines | iron_ore_pellet | copper_concentrates | ferro_nickel | zinc_concentrates | lead_concentrates | other",
    "commodity_name": "商品名称原文（如 铁矿块 IRON ORE LUMP）",
    "quality_name": "品质/品牌名称（如 Grasberg, Constancia, Red Chris, SP10F, Aranzazu 等）",
    "declared_quantity": "申报数量（数值）",
    "declared_quantity_unit": "申报数量单位（如 MT, KG）",
    "packing": "包装方式（如 In bulk, In bags）"
  },

  "weight": {
    "has_weight_data": true/false,
    "bl_weight_mt": "提单重量（MT）",
    "total_wet_weight_mt": "总湿重（MT）",
    "total_dry_weight_mt": "总干重/净干重（MT）",
    "moisture_at_discharge_pct": "卸货时水分（%）",
    "moisture_deduction_mt": "扣水量（MT）",
    "weighing_method": "称重方式描述（如 draft survey, bridge scale 等）",
    "lot_weights": [
      {
        "lot_id": "批次编号（如 P1）",
        "gross_weight_mt": null,
        "tare_weight_mt": null,
        "impurities_mt": null,
        "moisture_mt": null,
        "net_weight_mt": null
      }
    ]
  },

  "assay": {
    "analysis_state": "分析状态，如 dry_basis | as_received",
    "lot_data": [
      {
        "lot_id": "Lot编号（如 1, 2, ... 或 P1, P2 ...）",
        "lot_weight_wmt": "该Lot湿重（WMT，如有）",
        "lot_weight_dmt": "该Lot干重（DMT，如有）",
        "moisture_pct": "该Lot水分%（如有）",
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

  "notes": "报告中的重要备注、异常说明等"
}