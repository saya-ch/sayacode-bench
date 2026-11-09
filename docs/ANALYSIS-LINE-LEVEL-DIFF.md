# SWE-bench 失败 trial 行级 diff 分析

> **数据**：`C:\sb\hard\ab-ctx\{impact-350,v2v-main}\`（两批各 40 trial，SAYACODE 3.2.7），gold patch 来自
> `helper_code/sweap_eval_full_v2.jsonl`（731 条）。
> **方法**：通过/失败由各批 `FINAL-SUMMARY.json` 的 `agents.sayacode.trials[].effective_reward` 独立确定；
> 逐个读 `jobs/<job>/instance_*/agent/model.patch` 与 gold `patch` 做行级对齐；失败原因以
> `verify/jobs/verify-<job>/instance_*/verifier/{test-stdout,run-script-stdout,output.json}` 的**运行时输出**为准。
> **不做的事**：不采用 `failure-diffs/_index.json` 里的分类标签，不引用任何既有失败模式判断。
> **不确定的地方**在 §6 明示。

---

## 0. 一句话结论

33 个失败 trial 里，**只有 11 个是"测试跑起来但断言失败"**；**12 个根本没跑起来**（编译失败或测试收集失败），**9 个是空 patch（模型没改任何文件）**，1 个是改坏了既有功能。也就是说：**"模型改错了代码"只解释了约三分之一的失败**，另外三分之二是"改不出来"或"改出来跑不了"。

---

## 1. 失败 trial 全清单

两批合计 33 条（impact-350：16；v2v-main：17）。`partial` 是 verifier 的"必需测试通过比例"，`patch` 是 `model.patch` 字节数。

| # | 批次 | 任务 | r | patch(B) | partial | gold(B) | 失败路径 | 一行原因 |
|---|---|---|---|---|---|---|---|---|
| 1 | impact | flipt-9d25c | 1 | 195119 | 0.0 | 46578 | 编译失败 | `go build` 失败（2 个包） |
| 2 | impact | flipt-9d25c | 2 | 145242 | 0.0 | 46578 | 编译失败 | 同上 |
| 3 | v2v | flipt-9d25c | 1 | 190224 | 0.0 | 46578 | 编译失败 | 同上 |
| 4 | v2v | flipt-9d25c | 2 | 22965 | 0.0 | 46578 | 编译失败 | 同上 |
| 5 | impact | navidrome-0130c | 2 | 10555 | 0.0 | 8217 | 编译失败 | `r.getImageFiles undefined` |
| 6 | v2v | navidrome-0130c | 1 | 2478 | 0.0 | 8217 | 编译失败 | 同上 |
| 7 | v2v | navidrome-0130c | 2 | 1181 | 0.0 | 8217 | 编译失败 | 同上 |
| 8 | impact | vuls-4b680b | 2 | 1743 | 0.5 | 2598 | 编译失败 | `d.parsePkgInfo undefined` |
| 9 | v2v | vuls-4b680b | 2 | 2022 | 0.5 | 2598 | 编译失败 | 同上 |
| 10 | impact | qutebrowser-3e21c | 1 | 1173 | 0.0 | 5307 | 收集失败 | `AssertionError: <Ctrl+Alt+y>`（导入期） |
| 11 | v2v | qutebrowser-3e21c | 1 | 4022 | 0.0 | 5307 | 收集失败 | 同上 |
| 12 | v2v | ansible-a02e2 | 1 | 8167 | 0.0 | 7256 | 收集失败 | `ValueError: error parsing...` |
| 13 | impact | ansible-7e1a3 | 1 | 12356 | 0.0 | 10818 | 断言失败 | f2p 5/5 全败 |
| 14 | impact | ansible-7e1a3 | 2 | 15150 | 0.8 | 10818 | 断言失败 | f2p 1/5 败（`purge_LAG`） |
| 15 | impact | openlibrary-03095 | 1 | 2274 | 0.667 | 2469 | 断言失败 | f2p 1/2 败（`test_action_save`） |
| 16 | v2v | openlibrary-03095 | 2 | 2763 | 0.333 | 2469 | 断言失败 | f2p 2/2 败 |
| 17 | impact | qutebrowser-52708 | 1 | 2491 | 0.998 | 4736 | 断言失败 | f2p 2/4 败（`valid_values[text:bar]`、`[foo]`） |
| 18 | impact | element-web-772d | 1 | 729 | 0.951 | 19713 | 断言失败 | f2p 4/17 败（Multiple selection） |
| 19 | v2v | element-web-772d | 2 | 9680 | 0.915 | 19713 | 断言失败 | f2p 7/17 败 |
| 20 | v2v | element-web-772d | 1 | 12066 | 0.866 | 19713 | **仅 p2p 回归** | 0 个 f2p 失败，12 个 p2p 失败 |
| 21 | impact | flipt-756f0 | 2 | 11555 | 0.833 | 9626 | 断言失败 | `TestLoad/deprecated_-_ui_disabled_(YAML)` |
| 22 | v2v | flipt-756f0 | 2 | 3123 | 0.833 | 9626 | 断言失败 | 同上 |
| 23 | impact | flipt-8bd3604 | 2 | 6704 | 0.857 | 4835 | 断言失败 | `TestLeveledLogger`（JSON 字段格式） |
| 24 | v2v | flipt-8bd3604 | 2 | 5518 | 0.714 | 4835 | 断言失败 | 同上 |
| 25 | impact | openlibrary-03095 | 2 | **0** | — | 2469 | 空 patch | 无任何文件修改 |
| 26 | impact | flipt-756f0 | 1 | **0** | — | 9626 | 空 patch | 同上 |
| 27 | impact | element-web-772d | 2 | **0** | — | 19713 | 空 patch | 同上 |
| 28 | impact | navidrome-0130c | 1 | **0** | — | 8217 | 空 patch | 同上 |
| 29 | v2v | ansible-7e1a3 | 2 | **0** | — | 10818 | 空 patch | 同上 |
| 30 | v2v | qutebrowser-3d01 | 2 | **0** | — | 5567 | 空 patch | 同上 |
| 31 | v2v | qutebrowser-3e21c | 2 | **0** | — | 5307 | 空 patch | 同上 |
| 32 | v2v | flipt-756f0 | 1 | **0** | — | 9626 | 空 patch | 同上 |
| 33 | v2v | navidrome-6b3b4 | 1 | **0** | — | 10653 | 空 patch | 同上 |

> 9 个空 patch 的 job 都有正常的 `started_at`/`finished_at`（跨度 1–51 分钟），`result.json` 无 `exception`，说明**不是崩溃退出**，而是 agent 正常结束后没有任何文件改动被采集到。原因未查（见 §6）。

---

## 2. 行级对比：编译/收集失败（12 条）

这一类**测试根本没执行**，所以"行级 diff"不是用来找逻辑错，而是用来找**接口不匹配**——模型实现了某个功能，但名字/签名/字段与测试期望不符。

### 2.1 navidrome-0130c（3 条）：测试要 `getImageFiles`，模型没给这个方法

**运行时证据**（impact-350 r2，`run-script-stdout.txt`）：

```
scanner/refresher_test.go:36:20: r.getImageFiles undefined (type *refresher has no field or method getImageFiles)
scanner/refresher_test.go:59:20: r.getImageFiles undefined (type *refresher has no field or method getImageFiles)
FAIL	github.com/navidrome/navidrome/scanner [build failed]
```

**gold 的做法**（`db/migration/20221219112733_add_album_image_paths.go`）：

```diff
+alter table main.album add image_files varchar;
...
+	return forceFullRescan(tx)
```

并在 `model/album.go` 只加一个字段：

```diff
+	ImageFiles           string    `structs:"image_files" json:"imageFiles,omitempty"`
```

**模型的做法**（`impact-350` r2 patch）：

```diff
// 文件名完全不同：20220725000000_add_album_image_files.go（gold 是 20221219112733_add_album_image_paths.go）
+alter table album
+	add image_files text;
+	notice(tx, "A full rescan is recommended so albums pick up external cover art")   // gold 是 forceFullRescan(tx)
```

`model/album.go` 改成**双字段**：

```diff
+	ImageFiles           []string  `structs:"-" json:"imageFiles,omitempty" orm:"-"`
+	ImageFilesRaw        string    `structs:"image_files" json:"-" orm:"column(image_files)"`
```

并额外改了 gold 没碰的 `persistence/album_repository.go`、`persistence/helpers.go`，在持久化层手工编解码（模型自己的注释写"beego 版本不会自动绑定 slice 字段"）。

**判定**：这是**方案分歧 + 接口不匹配**。模型选择了"切片字段 + persistence 层编解码"的架构，gold 选择"单字符串字段"。测试期望的是 `refresher.getImageFiles(...)` 这个方法（gold 在 `scanner/refresher.go` 里加了它），模型**没有提供同名方法**，所以测试文件编译不过。模型的多文件改动本身可能是自洽的，但它与**测试代码写死的接口**不一致。

> 注意：partial=0.0 不能读成"全部测试失败"——这里测试一个都没跑，partial 是按"required 未通过"记的 0。

### 2.2 vuls-4b680b（2 条）：测试要 `parsePkgInfo`，模型没给

**运行时证据**：

```
scan/freebsd_test.go:239:15: d.parsePkgInfo undefined (type *bsd has no field or method parsePkgInfo)
FAIL	github.com/future-architect/vuls/scan [build failed]
```

**差异**：gold `scan/freebsd.go` 加了 28 行（含 `parsePkgInfo`），模型只加 25 行、**且没有这个方法名**。模型把 `models/scanresults.go` 的 4 行改得与 gold 一致（`added_common=4`），但 `scan/freebsd.go` 的 14 行共同 + 14 行缺失——核心的函数名对不上。

**判定**：**接口不匹配**（方法名/职责划分与测试期望不符），不是逻辑错。

### 2.3 flipt-9d25c（4 条）：改了 19 万字节，`go build` 仍然失败

**运行时证据**（impact-350 r1）：

```
FAIL	go.flipt.io/flipt/internal/server/evaluation [build failed]
FAIL	go.flipt.io/flipt/internal/server/ofrep [build failed]
Required tests: 8
Required tests that passed: 0
```

**规模对比**：gold 46,578B / 12 文件；model **195,119B / 10 文件**（impact r1）、190,224B / 6 文件（v2v r1）、22,965B / **1 文件**（v2v r2）。

**行级差异（impact r1，`rpc/flipt/ofrep/ofrep.pb.go`）**：

```
model +260 / gold +217，共同 96，缺失 80
model 额外多改 go.work.sum +926（gold 只 +1）
model 漏 2 个文件：internal/server/ofrep/bridge_mock.go、rpc/flipt/flipt.yaml
```

**判定**：模型在**生成代码（`.pb.go`）和依赖锁（`go.work.sum`）上大量改动**，同时漏掉 gold 改的手写桥接文件，最终编译失败。这不是"某一行写错"，而是**改动范围失控**：在自动生成文件上手工改，把依赖锁也带进来（+926 行），而真正需要改的 `ofrep/errors.go`（gold +47）只改了 13 行。

### 2.4 qutebrowser-3e21c（2 条）：导入期断言把整个测试模块打挂

**运行时证据**：

```
qutebrowser/keyinput/keyutils.py:494: in _convert_key
    assert isinstance(key, (int, Qt.KeyboardModifiers)), key
E   AssertionError: <Ctrl+Alt+y>
ERROR tests/unit/keyinput/test_bindingtrie.py - AssertionError: <Ctrl+Alt+y>
ERROR tests/unit/keyinput/test_keyutils.py - AssertionError: <Ctrl+Alt+y>
collected 0 items / 2 errors
```

**差异**：model patch 只有 1,173B（impact）/4,022B（v2v），gold 5,307B。模型只改了 8 行（impact），gold 改 26 行；模型在 `_convert_key` 里保留了/新增了一个 `assert`，而测试的类定义在**模块导入时**就调用了 `KeySequence(...)`，断言直接抛出 → **整个模块 collection 失败**。

**判定**：**改动不完整 + 引入了不该有的断言**。gold 的处理是把 `_convert_key` 改成容忍 `KeyInfo` 输入（新增 26 行含分支），模型只补了 8 行，留下的 assert 在导入路径上被触发。

### 2.5 ansible-a02e2（1 条）：pytest 收集期 `ValueError: error parsing...`

**运行时证据**：

```
=========================== short test summary info ============================
ERROR test/units/galaxy/test_collection_install.py - ValueError: error parsin...
ERROR gw0 / gw1 / gw3
4 errors in 4.45s
```

**行级差异**：gold 改 5 文件（含 `lib/ansible/galaxy/collection/galaxy_api_proxy.py`、changelog），model 改 4 文件，**漏了 `galaxy_api_proxy.py`**，且**多改了** `lib/ansible/galaxy/dependency_resolution/providers.py`（gold 没碰）。

`lib/ansible/cli/galaxy.py`：model +7 / gold +5，**共同 0**——模型加的 `--offline` 参数帮助文本与 gold 完全不同（见下节 3.1 的同类 diff）。

**判定**：漏改关键文件（`galaxy_api_proxy.py` 是 offline 模式的数据面）+ 改了不该改的文件，导致测试文件的 fixture 在收集期就抛 `ValueError`。具体是哪个 fixture 需要完整栈，`test-stdout.txt` 被截断，**无法确定**。

---

## 3. 行级对比：测试跑通但断言失败（11 条）

### 3.1 qutebrowser-52708（1 条）：模型删掉了 `valid_values` 并改了构造签名

**测试怎么用这个类**（`test_patch` 原文）：

```python
class TestStatusbarWidget:
    @pytest.fixture
    def klass(self):
        return configtypes.StatusbarWidget

    @pytest.mark.parametrize('value', ['text:bar', 'foo'])
    def test_validate_valid_values(self, klass, value):
        widget = klass(valid_values=configtypes.ValidValues('foo'))   # ← 显式传 valid_values
        assert widget.to_py(value) == value
```

**gold 的实现**（+13 行，无自定义 `__init__`）：

```diff
+class StatusbarWidget(String):
+    """A widget for the status bar. ..."""
+    def _validate_valid_values(self, value: str) -> None:
+        if value.startswith("text:"):
+            return
+        super()._validate_valid_values(value)
```

gold 同时保留 `configdata.yml` 的 `valid_values`（只把 `name: String` 改成 `name: StatusbarWidget`）。

**模型的实现**（+33 行，自定义 `__init__`）：

```diff
+class StatusbarWidget(String):
+    VALID_WIDGETS = ['url', 'scroll', 'scroll_raw', 'history', 'tabs', 'keypress', 'progress']
+    TEXT_PREFIX = 'text:'
+    def __init__(self, *, none_ok: bool = False, completions=None) -> None:
+        super().__init__(none_ok=none_ok, completions=completions,
+                         valid_values=ValidValues(*self.VALID_WIDGETS))   # ← 不接受外部 valid_values
```

并在 `configdata.yml` 里**删掉 10 行 valid_values**（`-` 行包括 url/scroll/scroll_raw/history/tabs/keypress/progress 七个条目）只留 `name: StatusbarWidget`。

**运行时证据**：`failed_f2p` 为 `test_validate_valid_values[text:bar]` 与 `[foo]`。测试调用 `klass(valid_values=...)` 时，模型的 `__init__` **没有 `valid_values` 形参** → `TypeError`。

**判定**：**接口契约理解错误（方向错）**。模型把"可注入白名单的校验类型"设计成"自带硬编码白名单的类型"，与题面（"accept predefined widget names from the valid values list"）和测试（显式注入 `ValidValues('foo')`）都相反。此外模型**漏改 `qutebrowser/mainwindow/statusbar/bar.py`**（gold 在那里加了 `text:` 前缀的 `TextBase` 渲染与 `_clear_widgets`），即使校验通过，`text:` 组件也不会显示。

> 这题 partial=0.998 极具迷惑性：1014 个测试里只失败 2 个，但**这 2 个正是 f2p**。partial 的分母包含大量 p2p，所以"partial 高"不等于"接近通过"。

### 3.2 flipt-8bd3604（2 条）：JSON 日志的 level 字段类型不符

**运行时证据**（impact-350 r2）：

```
--- FAIL: TestLeveledLogger
        	-ERROR	error	{"level": 10}
        	+DEBUG	debug	{"level": "DEBUG", "key": false}
        	+INFO	info	{"level": "INFO", "foo": "bar"}
        	+WARN	warn	{"level": "WARN", "alarm": 3.2}
        	+ERROR	error	{"level": "ERROR", "level": 10}
```

**差异**：model 在 `internal/server/audit/template/leveled_logger.go` 改了 51–52 行（gold 30 行，共同 14–16 行）。测试期望每条日志的 JSON 只有 `{"level": <数字>}`（slog 的原始 level 值），模型输出成 `{"level": "DEBUG", ...}`——**把 level 写成了字符串**，并把额外字段也塞进 JSON。

**判定**：**数据格式/语义理解错**。这是"方向错"的另一种形态：模型以为要输出"人类可读的 level 名"，而测试要的是 slog 的**数值** level（`10`、`-4` 等）。`level` 字段语义理解反了。

### 3.3 flipt-756f0（2 条）：漏改 deprecation 路径

**运行时证据**：

```
--- FAIL: TestLoad (0.02s)
    --- FAIL: TestLoad/deprecated_-_ui_disabled_(YAML) (0.00s)
Required tests: 6 / Required tests that passed: 5 / Missing tests: ['TestLoad']
```

**差异**：gold 改 8 文件（含 `internal/config/testdata/deprecated/ui_disabled.yml`、`internal/config/cache.go`、`config.go` 38 行），model impact r2 只改 6 文件、**漏 4 个**（CHANGELOG/DEPRECATIONS/两个 testdata yml），且 `internal/config/config.go` 只改 17 行（gold 38，共同 6）。v2v r2 更少：3,123B，只改 2 文件、漏 6 个。

**判定**：**漏改**。`deprecated_-_ui_disabled_(YAML)` 这个用例正好依赖被漏掉的 `testdata/deprecated/ui_disabled.yml` 与 `config.go` 里的 deprecation 处理。属于"功能只做了一半"。

### 3.4 ansible-7e1a3（2 条）：新模块从零写，实现与 gold 不同

**规模**：gold 328 行（新文件 `lib/ansible/modules/network/icx/icx_linkagg.py`）；model r1 461 行、r2 461 行（都是新文件）。**共同行只有 108**（主要是 DOCUMENTATION 模板段落）。

**运行时证据**：r1 `failed_f2p=5/5`（全败），r2 `failed_f2p=1/5`（只剩 `test_icx_linkage_purge_LAG`）。

**判定**：这是"**从零实现新模块**"，模型写出的代码比 gold 多 40%，函数划分与 gold 不同。r2 只差一个 `purge` 用例，说明大部分功能是对的，但 `purge`（清空未声明的 LAG）这条路径没实现对。**不是漏改，是某条分支的实现缺失/错误**。具体哪一段错需要看 `icx_linkagg.py` 的 purge 逻辑与测试断言，本报告未逐行比对（461 行新文件，共同行仅 108，逐行对齐价值低）。

### 3.5 openlibrary-03095（2 条）：`find_keys` 只认字符串

**gold**（`scripts/new-solr-updater.py`，+45 行）：

```diff
+def find_keys(d: Union[dict, list]) -> Iterator[str]:
+    if isinstance(d, dict):
+        if 'key' in d:
+            yield d['key']            # ← 无条件 yield
+        for val in d.values():
+            yield from find_keys(val)
```

**模型**（+38 行）：

```diff
+def find_keys(d):
+    if isinstance(d, dict):
+        for k, v in d.items():
+            if k == 'key' and isinstance(v, str):   # ← 只 yield 字符串
+                yield v
```

**运行时证据**：r1 失败 `test_action_save`；v2v r2 失败 `test_action_save` + `test_move_edition`。

**判定**：**实现细节偏离**（多了 `isinstance(v, str)` 过滤）。若测试数据里有非 str 的 `key`（或需要 yield 非 str），就会漏。同时 gold 还改了 8 行删除（用来在 `parse_log` 里把新旧 key 一起 reindex），模型只删 3 行——**漏了"previous doc keys"那一半**，与题面 "must include both current and previous document keys" 直接相关。

### 3.6 element-web-772d（3 条：2 断言 + 1 回归）：改动量与 gold 差一个数量级

| trial | model patch | 文件数 | gold 文件数 | 漏文件 | 结果 |
|---|---|---|---|---|---|
| impact r1 | 729B | 1 | 9 | 8 | f2p 4/17 败 |
| v2v r2 | 9,680B | 2 | 9 | 7 | f2p 7/17 败 |
| v2v r1 | 12,066B | 4 | 9 | 6 | **0 f2p 失败，12 p2p 失败** |

**gold 的改动面**：`src/components/views/settings/devices/`（`FilteredDeviceList.tsx` +52、`DeviceTile.tsx`、`SelectableDeviceTile.tsx`）、`src/components/views/elements/AccessibleButton.tsx`、3 个 `.pcss`、`src/i18n/strings/en_EN.json`。

**impact r1 只改了 1 个文件、1 行**（`SelectableDeviceTile.tsx` +1，gold 在同一文件 +2），**8 个文件全漏**。但它 partial=0.951、17 个 f2p 只败 4 个——说明这题的 f2p 大部分落在既有测试上，漏改的新 UI 只影响 4 个"Multiple selection"用例。

**v2v r1 是唯一一条"改坏了"**：f2p 全过，但 12 个 p2p 失败（例：`SessionManagerTab | goes to filtered list from security recommendations`）。**判定：过度修改导致回归**。

---

## 4. 分类统计

| 类别 | 条数 | 占比 | 特征 |
|---|---:|---:|---|
| **D1 空 patch（无产出）** | 9 | 27% | 正常结束、无异常、无文件修改 |
| **D2 编译/收集失败（跑不了）** | 12 | 36% | Go `build failed` 9 条；pytest collection error 3 条 |
| **D3 f2p 断言失败（跑通但错）** | 11 | 33% | 其中"接口/格式方向错" 4 条、"漏改" 5 条、"实现分支缺失" 2 条 |
| **D4 仅 p2p 回归（改坏）** | 1 | 3% | element-web-772d v2v r1 |
| 合计 | 33 | 100% | |

按"是否为代码问题"再切分：

| 视角 | 条数 |
|---|---:|
| 根本没写代码（空 patch） | 9 |
| 写了但跑不起来（编译/收集） | 12 |
| 跑起来但不符合测试 | 11 |
| 跑起来且符合新测试、但破坏旧测试 | 1 |

**方向错的实例**（理解错需求，不只是漏改）：

1. **qutebrowser-52708**：把"可注入 valid_values 的类型"改成"硬编码白名单 + 改构造签名"，与测试的调用方式冲突。
2. **flipt-8bd3604**：把 slog 的**数值** level 写成**字符串** level，字段语义反了。
3. **navidrome-0130c**：选了不同的持久化架构（切片+编解码 vs 单字符串），没提供测试期望的 `getImageFiles` 方法。
4. **vuls-4b680b**：没提供测试期望的 `parsePkgInfo` 方法。
5. **flipt-9d25c**：在生成代码（`.pb.go`）和依赖锁（`go.work.sum` +926）上大改，漏掉手写桥接文件。

其中 1、2 是**语义/契约层**的方向错（最值得修）；3、4 是**接口名**不匹配；5 是**改动范围失控**。

---

## 5. 最值得修的一类：D2（编译/收集失败，12 条，占非空 patch 的 50%）

**理由（按重要性排序）**：

1. **占比最高且最容易被消除**。12/24 个非空 patch 连编译都不过——这不是"能力上限"，而是"改完没验证"。模型写出了代码，但代码里引用了不存在的方法、留了会抛的断言、改了生成文件。
2. **根因高度集中，可规则化**：
   - 9 条 Go：`build failed` 全部是**测试文件引用的符号不存在**（`getImageFiles`、`parsePkgInfo`）或**生成代码被手改**（flipt-9d25c）。只要在提交前跑一次 `go build ./...` / `go vet`，至少 7 条能避免。
   - 3 条 Python：`collection error` 是**模块导入期抛异常**（`assert` / `ValueError`）。跑一次 `pytest --collect-only` 就能暴露。
3. **与"漏改"不同，这类失败不能靠加 token/加步数解决**——模型可能已经"认为自己做完了"。必须由 harness 强制"改完必须本地验证"，而不是靠模型自觉。
4. **收益可量化**：若这 12 条中有 7 条（Go 的符号缺失 + Python 的收集失败）能被"编译/收集检查"拦住并让模型继续修，通过率上限会从 24/40 提升到 31/40 量级（+17.5pp）——这是当前失败结构里最大的一块。

**次优**：D3 中的"接口/格式方向错"（4 条）。这类需要模型**读测试代码**（test_patch 在题面里通常不可见，但仓库里往往有同类测试），属于提示词/策略层面可改进的。

**不建议优先修**：D1（空 patch 9 条）。它不是"改错"，而是"没改"，原因未查（§6），可能是任务太难/超时/模型放弃，需要先看轨迹再定。

---

## 6. 我无法判断的

1. **9 个空 patch 为什么没产出**。job 有正常起止时间、无 exception，但 `audit.jsonl` 的格式与我的解析器不匹配（解析后 `type`/`tool_name` 字段为空），无法统计"模型是否读了文件、是否尝试写"。**要回答这个，需要按该 JSONL 的真实 schema 重写解析器，或直接看 `events.jsonl` / `worker-result.json` 的原始结构。**本报告不猜。
2. **ansible-a02e2 的 `ValueError: error parsing...` 完整栈**。`test-stdout.txt` 被截断到 `error parsin...`，无法确定是哪个 fixture/模块。需要完整 `run-script-stdout.txt` 的前半段。
3. **ansible-7e1a3 的 purge 分支错在哪**。新文件 461 行、与 gold 共同行仅 108，逐行对齐的信息量低。要定位需读 `icx_linkagg.py` 的 `purge` 逻辑与 `test_icx_linkage_purge_LAG` 的断言，本报告未做。
4. **element-web-772d v2v r1 的 12 个 p2p 回归具体怎么坏的**。只知道是 `SessionManagerTab` 相关用例，未逐行对比 model 与 gold 在该文件的改动。
5. **flipt-9d25c 的编译错误具体行**。`run-script-stdout.txt` 只给了 `[build failed]`，没有 `go build` 的 stderr 原文（Go 的 test 输出把编译错误写到了被截断的部分）。
6. **`failure-diffs/` 里 14 组样本与 FINAL-SUMMARY 的对应关系**。文件大小与 `FINAL-SUMMARY.patch` 字段不完全相等（例：`05-漏改-element-web-7.model.patch` 12,348B，而 impact/v2v 的 element-772d patch 是 729/12,066/9,680B），推测样本做过规范化（换行符/git 头），但**未逐字节核对**。本报告因此直接从 `jobs/` 读原始 patch，未使用这 14 组。

---

## 7. 复现

```powershell
# 失败清单（独立于任何既有分类）
uv run --no-sync python C:\sb\tmp\explore\line_diff.py      # → line_diff_out\summary.json
# 测试级证据
uv run --no-sync python C:\sb\tmp\explore\verify_fail.py   # → line_diff_out\verify_fail.json
# 失败路径分类 + 错误原文
uv run --no-sync python C:\sb\tmp\explore\classify_fail.py
# 单个 trial 的 gold vs model 逐 hunk
uv run --no-sync python C:\sb\tmp\explore\show_diff.py impact-350 qutebrowser-52708364 1
```

**数据位置**

| 内容 | 路径 |
|---|---|
| 通过/失败判定 | `C:\sb\hard\ab-ctx\{impact-350,v2v-main}\FINAL-SUMMARY.json` → `agents.sayacode.trials` |
| model patch | `...\sayacode\jobs\<job>\instance_*\agent\model.patch` |
| 运行时证据 | `...\sayacode\verify\jobs\verify-<job>\instance_*\verifier\{test-stdout,run-script-stdout,output.json}` |
| gold patch | `...\helper_code\sweap_eval_full_v2.jsonl`（字段 `patch` / `test_patch` / `FAIL_TO_PASS`） |
