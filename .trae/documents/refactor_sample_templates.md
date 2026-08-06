# 示例模板与模板变量填写改造计划

## 背景与目标

当前“模板变量填写”入口在工作台，对所有含 `{{变量}}` 的模板生效。用户希望：
1. 将“模板变量填写”从工作台移除，仅用于“示例模板”。
2. 示例模板不在工作台显示，只能在模板管理中查看/使用。
3. 在模板管理全屏编辑示例模板时，进入“只读内容 + 填写变量 + 另存为模板”模式：用户不能修改示例原文，只能修改变量值，保存后生成新的普通模板（变量已被替换），原示例模板保持不变。
4. 变量填写区上方的模板列表风格与整体统一、长度一致；下方变量输入使用已有大文本框样式（`.input-textarea`），不再使用小行内输入。

## 核心设计决策

- **新增字段 `is_sample`**：在 `PromptTemplate` 增加布尔字段区分“示例模板”。不改动 `category='example'`（范例文章/风格参考）的既有语义，避免破坏智能风格链。
- **工作台排除示例模板**：模板分组接口 `/api/templates/grouped` 默认排除 `is_sample=True`，工作台因此看不到示例模板。
- **模板管理保留全部模板**：示例模板在列表中显示“示例”徽标，点击进入示例编辑模式。
- **变量填写移入示例编辑器**：保留一个简洁的示例模板 tab 栏（替代原弹窗顶部的模板标签），下方用 `.input-textarea` 大文本框收集变量值。
- **另存为模板**：通过新接口 `/api/templates/from-sample` 将示例内容中的 `{{变量}}` 替换后创建普通模板。

## 关键文件

- `database/models.py`
- `database/migrations.py`
- `database/seed.py`
- `services/template_service.py`
- `services/prompt_assembler.py`（复用 `fill_variables`）
- `routes/template_routes.py`
- `routes/support/generation_request.py`
- `templates/index.html`
- `static/js/app.js`
- `static/css/style.css`

---

## 后端改造

### 1. 模型层：`database/models.py`

在 `PromptTemplate` 中新增字段：

```python
is_sample = db.Column(db.Boolean, nullable=False, default=False)
```

`to_dict()` 返回值中加入 `'is_sample': self.is_sample`。

### 2. 数据库迁移：`database/migrations.py`

在 `apply_sqlite_migrations` 中幂等补齐列：

```python
if 'is_sample' not in template_columns:
    db.session.execute(db.text(
        "ALTER TABLE prompt_templates ADD COLUMN is_sample BOOLEAN NOT NULL DEFAULT 0"
    ))
```

### 3. 种子数据：`database/seed.py`

首次启动时，将**含变量**且非 `category='example'` 的种子模板标记为示例模板：

- 修改 `SEED_TEMPLATES` 中的条目，增加 `'is_sample': True`。
- 同步修改 `create_template(...)` 调用，传入 `is_sample=tpl.get('is_sample', False)`。
- `category='example'` 的范例文章（风格参考）保持 `is_sample=False`。

### 4. 服务层：`services/template_service.py`

- `create_template(...)` 增加 `is_sample=False` 参数并写入模型。
- `update_template(...)` 增加 `is_sample=None` 参数；允许修改该标记。
- `get_all_templates(...)` 增加 `exclude_samples=False` 参数，为真时过滤 `is_sample=False`。
- 新增 `get_sample_templates()`：返回所有未过期的示例模板（过滤旧版本）。
- 新增 `create_template_from_sample(sample_id, name, category, description, variable_values)`：
  1. 读取原示例模板，校验 `is_sample=True`。
  2. 调用 `services.prompt_assembler.fill_variables` 替换 `{{变量}}`。
  3. 使用 `create_template` 创建一条 `is_sample=False` 的新模板。
  4. 原示例模板内容、版本保持不变。

### 5. 路由层：`routes/template_routes.py`

- `GET /api/templates/grouped`：调用 `get_templates_by_category(exclude_samples=True)`，工作台只能拿到普通模板。
- `GET /api/templates`：默认包含示例模板；可通过 `include_samples=false` 排除。
- `GET /api/templates/samples`：返回所有示例模板列表，供示例编辑器顶部 tab 使用。
- `POST /api/templates/from-sample`：请求体 `{sample_id, name, category, description, variable_values}`，调用 `create_template_from_sample`。
- `PUT /api/templates/<id>`：如果目标模板 `is_sample=True`，拒绝修改 `name/category/content/description/style_strength/sort_order/is_active`，仅允许将 `is_sample` 改为 `False`（如需后续编辑原文）。
- `POST /api/templates` 与 `PUT /api/templates/<id>`：`allowed_fields` 加入 `is_sample`。

### 6. 生成请求防御：`routes/support/generation_request.py`

在 `GenerationRequest.load_templates()` 中，无论按 ID 加载还是全量加载，都过滤掉 `is_sample=True` 的模板，防止示例模板意外进入提示词拼接。

---

## 前端改造

### 1. HTML：`templates/index.html`

**移除工作台变量入口**
- 删除 `#variables-section`（变量值填写按钮区）。
- 删除页面底部 `#variables-modal`（模板变量弹窗）。

**全屏模板编辑器增加示例模式**
在 `#template-editor-panel > .editor-body` 内：
- `.document-meta-bar` 增加开关：
  ```html
  <label class="switch-label">
      <input type="checkbox" id="edit-template-is-sample"> 设为示例模板
  </label>
  ```
- `.markdown-toolbar` 上方插入示例模板 tab 栏：
  ```html
  <div id="sample-template-tabs" class="sample-template-tabs" style="display:none;"></div>
  ```
- `.markdown-workspace` 下方插入变量填写区：
  ```html
  <div id="sample-variables-panel" class="sample-variables-panel" style="display:none;">
      <div class="sample-variables-list" id="sample-variables-list"></div>
  </div>
  ```
- `.editor-header-actions` 增加“另存为模板”按钮：
  ```html
  <button id="btn-save-as-template" class="btn btn-primary" type="button" style="display:none;">另存为模板</button>
  ```

### 2. JS：`static/js/app.js`

**从工作台彻底移除变量功能**
- 删除 `updateVariablesPanel()` 整个函数。
- 删除 `getEditableValue()`、`updateVariableCount()`、`setVariablesModal()` 及其事件绑定。
- 工作台生成/预览时 `variable_values` 固定传 `{}`。
- `saveWorkspaceDraft()` / `restoreWorkspaceDraft()` 移除 `variableValues` 相关逻辑。
- `loadWorkspaceTemplates()` 移除 `updateVariablesPanel()` 调用。

**工作台模板面板过滤示例模板**
- `renderWorkspaceTemplates(grouped)`：渲染前过滤 `tpl.is_sample`，计数也仅统计非示例模板。
- `getActiveTemplateIds()` 同样过滤 `is_sample`。

**模板管理列表**
- `renderTemplateList()`：对 `tpl.is_sample` 的项显示 `<span class="sample-badge">示例</span>`。
- 点击普通模板 → 原普通编辑模式；点击示例模板 → 进入示例编辑模式。

**示例编辑器逻辑（新增）**
- `loadSampleTemplates()`：调用 `/api/templates/samples`，缓存到 `state.sampleTemplates`。
- `openTemplateEditor(templateId)`：获取模板后，根据 `tpl.is_sample` 分支：
  - `true` → `enterSampleMode(tpl)`
  - `false` → 原普通编辑流程
- `enterSampleMode(tpl)`：
  1. 设置 `#edit-template-content` 为 `readonly` / `disabled`，并渲染只读预览。
  2. 隐藏 `.markdown-toolbar` 的格式按钮（仅保留预览切换）。
  3. 显示 `#sample-template-tabs`，使用 `.variables-template-tab` 类渲染所有示例模板 tab，当前项加 `active`；点击切换示例模板。
  4. 显示 `#sample-variables-panel`，遍历 `tpl.variables`，为每个变量生成：
     ```html
     <label class="sample-variable-item">
         <span>{{变量名}}</span>
         <textarea class="input-textarea" data-var="变量名" rows="4"></textarea>
     </label>
     ```
  5. 名称输入框提示“新模板名称”，分类下拉默认保持原示例分类（可修改）。
  6. 隐藏 `#btn-save-template`，显示 `#btn-save-as-template`。
  7. 绑定 `#btn-save-as-template` → `saveSampleAsTemplate()`。
- `saveSampleAsTemplate()`：
  1. 校验新模板名称非空。
  2. 收集 `#sample-variables-list textarea[data-var]` 的值。
  3. POST `/api/templates/from-sample`。
  4. 成功后提示，并可选打开新创建的普通模板或关闭编辑器。

**普通编辑器补充**
- `openTemplateEditor(null/普通模板)`：根据 `tpl.is_sample` 显示/隐藏 `#edit-template-is-sample` 开关。
- `saveTemplate()`：提交数据中加入 `is_sample: $('#edit-template-is-sample').checked`。

### 3. CSS：`static/css/style.css`

**复用并修复 `.variables-template-tab`**
当前样式已存在但 JS 未使用。改为等宽、风格统一的 tab：

```css
.variables-template-tab {
    flex: 1 1 0;
    min-width: 0;
    padding: 8px 10px;
    border: 1px solid var(--line);
    border-radius: 8px;
    color: var(--muted);
    background: var(--surface-2);
    font-size: 12px;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.variables-template-tab.active {
    color: var(--jade);
    border-color: var(--jade);
    background: var(--jade-soft);
    box-shadow: inset 0 0 0 1px var(--jade);
}
.sample-template-tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 10px;
}
```

**示例编辑器专属样式**

```css
#edit-template-content:read-only,
#edit-template-content:disabled {
    background: var(--surface-2);
    color: var(--muted);
}
.sample-variables-panel {
    margin-top: 14px;
    padding: 16px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--surface);
}
.sample-variables-list {
    display: grid;
    gap: 12px;
}
.sample-variable-item {
    display: grid;
    gap: 6px;
}
.sample-variable-item span {
    font-size: 12px;
    font-weight: 650;
    color: var(--jade);
}
.sample-badge {
    margin-left: 6px;
    padding: 1px 6px;
    border-radius: 10px;
    background: var(--jade-soft);
    color: var(--jade-deep);
    font-size: 10px;
}
```

---

## 新用户流程

| 场景 | 表现 |
|---|---|
| 工作台 | 左侧模板面板仅显示普通模板；无“模板变量填写”入口；生成时不传变量值。 |
| 模板管理列表 | 普通模板与示例模板并列，示例模板带“示例”徽标。 |
| 点击普通模板 | 进入普通全屏编辑，可改内容、分类，可勾选“设为示例模板”。 |
| 点击示例模板 | 进入示例编辑模式：内容只读，顶部等宽示例 tab 栏，下方 `.input-textarea` 大文本框填写变量，按钮为“另存为模板”。 |
| 切换 tab | 直接切换到其他示例模板并渲染其变量区，不保存当前填写内容。 |
| 另存为模板 | 后端替换 `{{变量}}` 后创建新的普通模板；原示例模板版本、内容不变。 |
| 生成文章 | 示例模板不会进入生成流程；普通模板中的未填充变量按原样进入提示词。 |

---

## 验证步骤

1. 启动应用，确认 `prompt_templates` 表已存在 `is_sample` 列，无报错。
2. 进入“模板管理”：
   - 示例模板显示“示例”徽标。
   - 点击示例模板进入全屏编辑器：内容只读、顶部 tab 风格统一且长度一致、下方变量区为大文本框。
3. 填写变量后点击“另存为模板”：
   - 输入新模板名称与分类（默认原示例分类）。
   - 确认新模板创建成功，内容中 `{{变量}}` 已被替换。
   - 返回示例模板，确认原文未变。
4. 回到工作台：
   - 左侧模板面板不出现示例模板。
   - 没有“模板变量填写”入口。
5. 启用若干普通模板并生成文章：
   - 生成流程正常结束。
   - 提示词预览中普通模板的未填充变量保持原样。
6. 在模板管理中编辑一个普通模板，勾选“设为示例模板”并保存：
   - 确认该模板从工作台消失，再次点击进入示例编辑模式。

---

## 待产品确认（可选）

1. **种子数据**：首次安装时，含变量的种子模板将全部作为示例模板。如需保留部分可直接参与生成的普通模板，需额外准备无变量的默认模板。
2. **未填充变量处理**：普通模板中的 `{{变量}}` 在生成时保持原样。如需自动剔除或提示，可后续扩展。
