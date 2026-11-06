# VastaCore 终检增补对拍：登记缺口清偿（2026-11-06）

**承接**：[project-final-review-2026-09-14.md](project-final-review-2026-09-14.md)
终检判定为「PASS with registered gaps」——FR partial 4 条、NFR
partial 4 条 + absent 1 条。本增补逐条对拍清偿结果；方法沿用终检
四链口径（PRD 文字 → 承载 Story → sprint-status → 模块 + 测试断言体）。

基线：HEAD=5a6ac43；门禁 1315 passed + 5 skipped、ruff 0、
lint-imports 5/5 KEPT、流/事件目录双守卫零漂移（22 流 / 122 事件型）。

## 一、FR 四条 partial 清偿对拍（终检 §一 表）

| FR | 终检缺口 | 清偿 Story | 证据锚 | 判定 |
|---|---|---|---|---|
| FR-002 | middleware/sidecar 两接入形态未建 | 8.14 / 8.15 | test_middleware.py::test_wrapped_decide_walks_six_segments（dict 进出六段链）；test_sidecar.py::test_spawn_ready_handshake_and_shutdown（子进程 ready-file 握手 + 优雅退 0）+ test_full_loopback_contract | ✅ 五形态全量 |
| FR-015 | 音视频清单形态（不触真实字节） | 8.16 | test_media_real_bytes.py::test_slice_frames_match_source（WAV 逐帧对源）；test_real_byte_coordinates_verifiable（MP4 采样表坐标对源字节复核） | ✅ 真实字节 |
| FR-016 | OCR/ASR 零实现、embedding 演示级 | 8.16 | test_transcribe_digit_sequence（DTMF Goertzel 真实转写）；test_recognizes_rendered_text[1/3]（模板 OCR 原生/×3）；test_similarity_separates_lexically_related（词法嵌入 L2+余弦可分）；注入面 test_engine_injection_replaces_default / fail-closed | ✅ 注入面 + 封闭域真实参考实现（method/vocabulary/charset 溯源） |
| FR-084 | 商业分发子面未建 | 12.12 | test_plugin_commerce.py::test_paid_without_entitlement_blocks_pull（付费无凭据拒）+ test_purchase_unblocks_pull + test_free_and_unlisted_pull_unchanged（自由分发后向兼容） | ✅ 定价-购买-凭据-拉取闸闭环 |

**FR 终态：82 条 delivered 82 / partial 0 / absent 0。**

## 二、NFR 五条缺口清偿对拍（终检 §三 表）

| NFR | 终检缺口 | 清偿 Story | 证据锚 | 判定 |
|---|---|---|---|---|
| 012 无障碍 | absent（Console 未建） | 10.14 | test_console.py::test_skip_link_first_focusable / test_native_elements_no_js_handlers / test_form_label_associated / test_table_caption_and_scope | ✅（工程可验面：skip link、原生元素、label、caption+scope、焦点样式、对比色） |
| 013 国际化 | UI/时间/数字/策略描述零实现 | 10.14 | test_locale_switch_changes_catalog_and_lang / test_time_localization_differs / test_number_grouping / test_event_descriptions_localized + test_rendering_does_not_write_events（事件语义稳定） | ✅ |
| 004 SLO | 达成度测量缺 | 9.15 | test_ops_slo.py::test_attainment_and_error_budget + test_no_data_is_not_fake_100（无数据不伪造） | ⚠️→✅ 工程面（测量机制交付；生产月度统计属地运营——登记不变） |
| 006 扩展 | 真分布式部署 | 9.15 | test_multiprocess_store.py（3 OS 进程并发共享单库、每流单写者分区契约、完整性绿） | ⚠️→✅ 工程面（真跨机部署属地运营——登记不变） |
| 014 耐久 | RPO/RTO 达标测量与定期编排 | 9.15 | test_rto_rpo_measured_and_gated + test_slo_violation_fails_drill（门判有牙齿）+ test_scheduler_drives_drills_via_executor（cron 定期编排） | ⚠️→✅ 工程面（生产多区域演练属地运营——登记不变） |

**NFR 终态：工程可验面 15/15 交付；004/006/014 的属地运营执行部分
维持登记（终检口径「数字由真实运营数据产生」——不伪称完成）。**

## 三、本轮附带清偿（非终检登记项，随过程发现）

| 项 | 内容 | 证据 |
|---|---|---|
| darwin 可移植性 | 沙箱降限两步式 + 按资源尽力（macOS RLIMIT_AS EINVAL——此前本 Mac 上 6 测恒红，内存限额测试假通过）；Windows 基线不受影响 | df160b1；test_model_lab.py darwin skip 注记 |
| CI 门禁恢复 | 11 月 examples/cua 提交带 39 个 ruff 违例（CI 自 589be29 起红）——清零 | df160b1 |
| 仓库簿记 | examples/rag 入库（根 README 已链接；BYOK 无硬编码密钥）；MIGRATED-TO-Dev.txt 失实注记移除（本 Mac 仓库即主仓） | 72103cc |

## 四、Story 簿记

新增 Story 六条全部 done（Story 文档 + epics.md AC + sprint-status 回写）：

- 8.14 middleware（FR-002 第四形态）
- 8.15 sidecar（FR-002 第五形态）
- 8.16 多模态真实字节与识别引擎面（FR-015/016）
- 9.15 运营达标工程面（NFR-004/006/014）
- 10.14 Console 最小可用面（NFR-012/013）
- 12.12 插件商业分发子面（FR-084）

测试基线变化：终检 1249 passed + 5 skipped → **1315 passed + 5
skipped**（+66：middleware 5 + sidecar 6 + 媒体真实字节 13 +
commerce 14 + console 18 + ops/SLO 9 + 多进程 1）。

## 五、收口判定

**登记缺口清偿：通过（PASS, gaps cleared）**——FR 82/82 delivered、
NFR 工程可验面 15/15；属地运营三项（004/006/014 的生产执行）维持
登记并有 owner（运营），与终检口径一致不伪称。PRD §12 九条开放
问题不属工程缺口（决策门——确认时点在册），维持原状。

---

*审计方法同终检：四链对拍 + 锚点测试实跑（本轮全量门禁绿即基线）。*
