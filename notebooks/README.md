# Notebooks Guide

`notebooks/` 现在按用途分组，不再平铺。

## 01_leaf_pipeline

- `leaf_pipeline_playground.ipynb`
  - 看原始材料 -> 抽取 -> 路由 -> 卡片的主链
- `leaf_card_agent_ocr_playground.ipynb`
  - 看 OCR / 笔记文本如何进入 leaf card 流程
- `mineru_ocr_playground.ipynb`
  - 看 PDF / 图片如何先被 MinerU 提取成 markdown/json/txt

## 02_binding

- `wrong_question_binder_playground.ipynb`
  - 测错题绑定、Top-K 候选、是否调用 embedding

## 03_review

- `review_scheduler_playground.ipynb`
  - 看知识点 / 题目的优先级排序
- `review_bundle_playground.ipynb`
  - 看 review bundle 如何组装
- `review_session_demo.ipynb`
  - 看学生点击按钮后下一轮推荐如何变化

## 04_memory

- `student_memory_store_profile_demo.ipynb`
  - 看事件入库与画像重建
- `diagnosis_coach_memory_profile_demo.ipynb`
  - 看 diagnosis / coach / memory 的联动
- `coach_memory_bias_compare_demo.ipynb`
  - 看有无长期画像时 coach 策略差异
- `end_to_end_memory_rule_demo.ipynb`
  - 看 memory -> rules -> coach/review 的完整演示

## 05_system

- `teachagent_system_overview.ipynb`
  - 四部分总集成版，偏技术验证
- `teachagent_user_walkthrough.ipynb`
  - 四部分轻展示版，偏用户演示

## legacy

- 旧教学线 / 早期 demo
- 这些 notebook 先保留，但不建议作为当前主线入口

## 推荐顺序

如果你只是想快速看现在系统能做什么：

1. `05_system/teachagent_user_walkthrough.ipynb`
2. `05_system/teachagent_system_overview.ipynb`

如果你是要排查某个模块：

1. 先看对应分组
2. 再看 `scratch/` 里的执行产物
