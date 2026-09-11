const icons = {
  grid: '<svg viewBox="0 0 24 24"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/></svg>',
  upload: '<svg viewBox="0 0 24 24"><path d="M12 16V4m0 0 4 4m-4-4L8 8M5 20h14"/></svg>',
  sliders: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16M8 4v4m9 2v4m-6 2v4"/></svg>',
  map: '<svg viewBox="0 0 24 24"><path d="m4 6 6-2 5 2 5-2v14l-5 2-5-2-6 2zM10 4v14m5-12v14"/></svg>',
  chart: '<svg viewBox="0 0 24 24"><path d="M4 19V5m0 14h16M7 15l3-4 3 2 4-6"/></svg>',
  table: '<svg viewBox="0 0 24 24"><path d="M4 5h16v14H4zM4 10h16M4 15h16M10 5v14M16 5v14"/></svg>',
  settings: '<svg viewBox="0 0 24 24"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-5v3m0 12v3M4.93 4.93l2.12 2.12m9.9 9.9 2.12 2.12M3 12h3m12 0h3M4.93 19.07l2.12-2.12m9.9-9.9 2.12-2.12"/></svg>',
  download: '<svg viewBox="0 0 24 24"><path d="M12 4v11m0 0 4-4m-4 4-4-4M5 20h14"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="m8 5 11 7-11 7z"/></svg>',
  chevron: '<svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 10v6m0-9h.01"/></svg>'
};

const points = Array.from({ length: 72 }, (_, index) => {
  const x = 12 + (index * 37) % 76 + Math.sin(index * 1.7) * 4;
  const y = 14 + (index * 23) % 70 + Math.cos(index * 1.2) * 5;
  const people = Math.round(42 + x * 1.38 + Math.sin(index * 0.62) * 21);
  const night = Math.round(18 + y * 0.92 + Math.cos(index * 0.39) * 17);
  const gdp = Math.round(35 + x * 1.08 + y * 0.64 + Math.sin(index) * 24);
  return { id: index + 1, x, y, people, night, gdp, selected: index < 29 };
});

const state = {
  activeView: 'workspace',
  xMetric: 'people',
  yMetric: 'night',
  bandwidth: 0.62,
  kernel: '自适应带宽',
  weighting: '双平方核',
  selectedPoint: 18,
  chartMode: 'map',
  showPopulation: true,
  showNight: true,
  showGeometry: false,
  running: false,
  toast: ''
};

const metricNames = { people: '人口密度', night: '夜光遥感', gdp: '人均 GDP' };
const metricColors = { people: '#2d8c7c', night: '#e78338', gdp: '#4977b8' };

function icon(name) {
  return `<span class="icon">${icons[name]}</span>`;
}

function appTemplate() {
  return `
    <div class="app-shell">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">${icon('grid')}</div>
          <div>
            <div class="brand-name">空间数据交叉验证工作台</div>
            <div class="brand-meta">异源同质数据 · 精细尺度分析客户端</div>
          </div>
        </div>
        <div class="top-actions">
          <span class="status-dot"></span><span class="status-text">本地项目已保存</span>
          <button class="icon-btn" title="导出项目" data-action="export">${icon('download')}</button>
          <button class="avatar" title="当前用户">施</button>
        </div>
      </header>
      <div class="body">
        <aside class="sidebar">
          <div class="project-block">
            <span class="eyebrow">当前项目</span>
            <div class="project-name">武汉市多源空间数据验证</div>
            <div class="project-path">/projects/wuhan-2026</div>
          </div>
          <nav class="nav-list">
            ${navItem('workspace', '工作台', 'grid')}
            ${navItem('data', '数据管理', 'upload', '3')}
            ${navItem('preprocess', '预处理', 'sliders')}
            ${navItem('analysis', '空间分析', 'map')}
            ${navItem('results', '结果与报告', 'chart')}
          </nav>
          <div class="sidebar-bottom">
            <div class="data-health">
              <div class="health-label"><span>数据集状态</span><strong>已就绪</strong></div>
              <div class="health-bar"><span></span></div>
              <div class="health-note">3 类数据 · 12,486 条记录</div>
            </div>
            <button class="side-settings" data-view="settings">${icon('settings')}系统设置</button>
          </div>
        </aside>
        <main class="main-content">${mainContent()}</main>
      </div>
      <div id="toast" class="toast ${state.toast ? 'show' : ''}">${state.toast}</div>
    </div>
  `;
}

function navItem(view, label, iconName, badge = '') {
  return `<button class="nav-item ${state.activeView === view ? 'active' : ''}" data-view="${view}">
    ${icon(iconName)}<span>${label}</span>${badge ? `<b class="nav-badge">${badge}</b>` : ''}
  </button>`;
}

function mainContent() {
  if (state.activeView === 'data') return dataView();
  if (state.activeView === 'preprocess') return preprocessView();
  if (state.activeView === 'results') return resultsView();
  if (state.activeView === 'settings') return settingsView();
  return workspaceView();
}

function pageHeading(kicker, title, description, action = '') {
  return `<div class="page-heading">
    <div><div class="kicker">${kicker}</div><h1>${title}</h1><p>${description}</p></div>
    ${action}
  </div>`;
}

function workspaceView() {
  return `
    ${pageHeading('PROJECT WORKSPACE', '空间分析工作台', '对齐数据、构建空间权重，并快速定位多源数据的局部差异。',
      `<button class="primary-btn" data-action="run">${icon('play')}运行分析</button>`)}
    <div class="pipeline">
      ${step('01', '数据准备', '3 个数据源已加载', 'done')}
      ${step('02', '空间配准', '坐标与尺度已统一', 'done')}
      ${step('03', '局部建模', 'GWR 参数待运行', 'current')}
      ${step('04', '结果输出', '等待分析完成', '')}
    </div>
    <section class="workspace-grid">
      <div class="left-column">
        ${dataSourcesPanel()}
        ${metricsPanel()}
      </div>
      <div class="center-column">${analysisPanel()}</div>
      <div class="right-column">${parameterPanel()}${layersPanel()}</div>
    </section>
  `;
}

function step(number, title, note, status) {
  return `<div class="pipeline-step ${status}">
    <div class="step-number">${status === 'done' ? icon('check') : number}</div>
    <div><strong>${title}</strong><small>${note}</small></div>
    ${status === 'current' ? '<span class="step-live">进行中</span>' : ''}
  </div>`;
}

function dataSourcesPanel() {
  return `<section class="panel sources-panel">
    <div class="panel-header"><div><span class="section-label">数据源</span><h2>多源数据集</h2></div><button class="small-icon-btn" title="导入数据" data-action="upload">${icon('upload')}</button></div>
    <div class="source-list">
      ${sourceRow('people', '属性数据', '人口 · GDP', '人口普查2020.csv', 'teal', true)}
      ${sourceRow('night', '栅格数据', '夜光遥感', 'NPP-VIIRS-2024.tif', 'orange', true)}
      ${sourceRow('geometry', '几何数据', '道路 · 建筑物', 'LUCC-武汉.gpkg', 'blue', false)}
    </div>
    <button class="outline-btn full" data-action="upload">${icon('upload')}导入新数据</button>
  </section>`;
}

function sourceRow(key, title, subtitle, filename, color, checked) {
  return `<div class="source-row">
    <div class="source-icon ${color}">${icon(key === 'people' ? 'table' : key === 'night' ? 'grid' : 'map')}</div>
    <div class="source-copy"><strong>${title}</strong><span>${subtitle}</span><small>${filename}</small></div>
    <label class="switch"><input type="checkbox" data-layer="${key}" ${checked ? 'checked' : ''}><span></span></label>
  </div>`;
}

function metricsPanel() {
  return `<section class="panel">
    <div class="panel-header"><div><span class="section-label">评价指标</span><h2>全局一致性</h2></div><button class="text-btn">查看全部 ${icon('chevron')}</button></div>
    <div class="metric-list">
      ${metricRow('平均绝对误差', 'MAE', '8.42', '较上次 ↓ 12.4%', 'good')}
      ${metricRow('相关系数', 'R', '0.82', '显著正相关', 'good')}
      ${metricRow('均方根误差', 'RMSE', '13.67', '较上次 ↓ 6.8%', 'good')}
    </div>
  </section>`;
}

function metricRow(label, code, value, note, tone) {
  return `<div class="metric-row"><span class="metric-code">${code}</span><div><strong>${label}</strong><small>${note}</small></div><b class="${tone}">${value}</b></div>`;
}

function analysisPanel() {
  const selected = points.find((point) => point.id === state.selectedPoint);
  return `<section class="panel analysis-panel">
    <div class="panel-header analysis-header">
      <div><span class="section-label">局部精细尺度分析</span><h2>空间差异分布</h2></div>
      <div class="view-toggle"><button class="toggle-btn ${state.chartMode === 'map' ? 'active' : ''}" data-chart="map">${icon('map')}地图</button><button class="toggle-btn ${state.chartMode === 'scatter' ? 'active' : ''}" data-chart="scatter">${icon('chart')}散点图</button></div>
    </div>
    <div class="analysis-toolbar">
      <label>横轴 <select id="xMetric">${metricOptions(state.xMetric)}</select></label>
      <span class="relation">与</span>
      <label>纵轴 <select id="yMetric">${metricOptions(state.yMetric)}</select></label>
      <span class="toolbar-divider"></span>
      <button class="ghost-btn" data-action="reset">${icon('settings')}重置视图</button>
    </div>
    <div class="viz-area" id="vizArea">${state.chartMode === 'map' ? mapSvg() : scatterSvg()}</div>
    <div class="viz-footer"><div><span class="legend-dot high"></span>高一致性 <span class="legend-dot mid"></span>中等差异 <span class="legend-dot low"></span>显著差异</div><span>单击样本查看详情</span></div>
    <div class="selection-detail">
      <div class="selection-pin"></div><div><small>当前选中样本 · ID ${String(selected.id).padStart(4, '0')}</small><strong>江汉区 / 唐家墩街道</strong></div>
      <div class="selection-values"><span><small>人口</small><b>${selected.people}</b></span><span><small>夜光</small><b>${selected.night}</b></span><span><small>局部 R²</small><b class="teal-text">0.${Math.round(74 + state.bandwidth * 20)}</b></span></div>
    </div>
  </section>`;
}

function metricOptions(value) {
  return Object.entries(metricNames).map(([key, label]) => `<option value="${key}" ${key === value ? 'selected' : ''}>${label}</option>`).join('');
}

function mapSvg() {
  const circles = points.map((point) => {
    const delta = Math.abs(point.people - point.night);
    const fill = delta < 38 ? '#2d8c7c' : delta < 62 ? '#e6a05d' : '#d86659';
    const selected = point.id === state.selectedPoint;
    return `<circle cx="${point.x}%" cy="${point.y}%" r="${selected ? 1.65 : 0.9}" fill="${fill}" opacity="${point.selected ? 0.9 : 0.36}" class="${selected ? 'selected-point' : ''}" data-point="${point.id}"><title>样本 ${point.id}</title></circle>`;
  }).join('');
  return `<div class="map-wrap">
    <div class="map-grid"></div>
    <div class="map-label label-wuchang">武昌区</div><div class="map-label label-hanyang">汉阳区</div><div class="map-label label-jianghan">江汉区</div><div class="map-label label-hongshan">洪山区</div><div class="map-label label-jiangxia">江夏区</div>
    <svg class="map-svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="样本空间差异分布图">
      <path class="river" d="M0,35 C20,26 25,55 42,45 C58,35 63,25 77,37 C85,44 89,63 100,58 L100,72 C84,78 81,54 69,50 C55,45 48,62 34,60 C18,57 17,42 0,49Z"/>
      <path class="road road-a" d="M10,12 C28,30 22,47 42,54 S65,65 89,85"/><path class="road road-b" d="M22,88 C35,72 46,70 55,49 S67,23 84,10"/><path class="road road-c" d="M8,61 C31,58 48,39 94,41"/>
      ${state.showPopulation || state.showNight ? circles : ''}
    </svg>
    <div class="map-scale"><span></span><small>10 km</small></div>
    <div class="map-zoom"><button data-action="zoom-in">+</button><button data-action="zoom-out">−</button></div>
  </div>`;
}

function scatterSvg() {
  const xKey = state.xMetric;
  const yKey = state.yMetric;
  const xValues = points.map((point) => point[xKey]);
  const yValues = points.map((point) => point[yKey]);
  const xMin = Math.min(...xValues) - 8;
  const xMax = Math.max(...xValues) + 8;
  const yMin = Math.min(...yValues) - 8;
  const yMax = Math.max(...yValues) + 8;
  const dots = points.map((point) => {
    const x = 9 + ((point[xKey] - xMin) / (xMax - xMin)) * 84;
    const y = 88 - ((point[yKey] - yMin) / (yMax - yMin)) * 76;
    const selected = point.id === state.selectedPoint;
    return `<circle cx="${x}" cy="${y}" r="${selected ? 1.7 : 1}" fill="${metricColors[xKey]}" opacity="${point.selected ? .85 : .35}" class="${selected ? 'selected-point' : ''}" data-point="${point.id}"><title>样本 ${point.id}</title></circle>`;
  }).join('');
  return `<div class="scatter-wrap">
    <div class="axis-title axis-y">${metricNames[yKey]}</div><div class="axis-title axis-x">${metricNames[xKey]}</div>
    <svg class="scatter-svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="变量关系散点图">
      <path class="scatter-grid" d="M9 12H93M9 31H93M9 50H93M9 69H93M9 88H93M9 12V88M30 12V88M51 12V88M72 12V88M93 12V88"/>
      <path class="scatter-trend" d="M10 79 C27 68 43 62 57 53 S79 30 92 23"/>
      ${dots}
    </svg>
    <div class="scatter-stat"><span>局部拟合</span><strong>R² 0.74</strong><small>正相关趋势</small></div>
  </div>`;
}

function parameterPanel() {
  return `<section class="panel parameter-panel">
    <div class="panel-header"><div><span class="section-label">GWR MODEL</span><h2>模型参数</h2></div><span class="info-icon">${icon('info')}</span></div>
    <div class="control-group"><label>核函数</label><select id="kernel"><option>双平方核</option><option>高斯核</option><option>指数核</option></select></div>
    <div class="control-group"><div class="control-label"><label>带宽</label><output id="bandwidthValue">${state.bandwidth.toFixed(2)}</output></div><input id="bandwidth" type="range" min="0.1" max="1" step="0.01" value="${state.bandwidth}"><div class="range-hint"><span>局部</span><span>全局</span></div></div>
    <div class="control-group"><label>带宽策略</label><div class="segmented"><button class="${state.kernel === '固定带宽' ? 'active' : ''}" data-bandwidth-mode="固定带宽">固定带宽</button><button class="${state.kernel !== '固定带宽' ? 'active' : ''}" data-bandwidth-mode="自适应带宽">自适应带宽</button></div></div>
    <div class="control-group"><label>距离度量</label><select><option>投影坐标距离 (米)</option><option>大圆距离 (千米)</option></select></div>
    <div class="model-note"><span class="status-dot"></span><span>建议：当前样本量适合使用自适应带宽</span></div>
  </section>`;
}

function layersPanel() {
  return `<section class="panel layers-panel">
    <div class="panel-header"><div><span class="section-label">MAP LAYERS</span><h2>图层显示</h2></div></div>
    <div class="layer-row"><span class="layer-swatch population"></span><span>人口密度差异</span><label class="switch"><input type="checkbox" checked><span></span></label></div>
    <div class="layer-row"><span class="layer-swatch nightlight"></span><span>夜光遥感强度</span><label class="switch"><input type="checkbox" checked><span></span></label></div>
    <div class="layer-row"><span class="layer-swatch boundaries"></span><span>行政区边界</span><label class="switch"><input type="checkbox" checked><span></span></label></div>
    <div class="layer-row"><span class="layer-swatch sample"></span><span>样本点</span><label class="switch"><input type="checkbox" checked><span></span></label></div>
  </section>`;
}

function dataView() {
  return `${pageHeading('DATA CATALOG', '数据管理', '统一登记多源数据的来源、空间范围、坐标系与质量状态。',
    `<button class="primary-btn" data-action="upload">${icon('upload')}导入数据</button>`)}
    <section class="panel table-panel"><div class="panel-header"><div><span class="section-label">DATASETS · 03</span><h2>项目数据目录</h2></div><button class="outline-btn" data-action="export">${icon('download')}导出清单</button></div>
      <table><thead><tr><th>数据集</th><th>类型</th><th>空间范围</th><th>坐标系</th><th>记录 / 分辨率</th><th>状态</th><th></th></tr></thead>
      <tbody>${dataTableRow('人口普查2020', '属性数据', '武汉市行政区', 'CGCS2000', '2,815 条', '已配准', 'teal')}${dataTableRow('NPP-VIIRS-2024', '栅格数据', '武汉市域', 'WGS 84', '500 m', '待重采样', 'orange')}${dataTableRow('LUCC-武汉', '几何数据', '中心城区', 'CGCS2000', '9,674 要素', '已配准', 'teal')}</tbody></table>
    </section>
    <div class="info-strip"><div class="strip-icon">${icon('info')}</div><div><strong>数据质量检查通过</strong><p>未发现缺失坐标或重复主键。栅格数据建议在分析前完成空间重采样。</p></div><button class="text-btn" data-view="preprocess">去预处理 ${icon('chevron')}</button></div>`;
}

function dataTableRow(name, type, extent, crs, count, status, tone) {
  return `<tr><td><strong>${name}</strong><small>${name === '人口普查2020' ? 'CSV · 2026-09-08' : name === 'NPP-VIIRS-2024' ? 'GeoTIFF · 2026-09-09' : 'GeoPackage · 2026-09-08'}</small></td><td>${type}</td><td>${extent}</td><td><code>${crs}</code></td><td>${count}</td><td><span class="tag ${tone}">${status}</span></td><td><button class="kebab">···</button></td></tr>`;
}

function preprocessView() {
  return `${pageHeading('DATA PREPARATION', '预处理与空间配准', '将不同来源的数据统一到同一空间参考、尺度与分析单元。')}
    <div class="prep-grid"><section class="panel prep-flow"><div class="panel-header"><div><span class="section-label">PIPELINE</span><h2>标准化处理流程</h2></div><span class="tag teal">3 / 5 已完成</span></div>
      ${prepRow('01', '数据质量检查', '缺失值、异常值、重复记录', '已完成', 'done')}${prepRow('02', '空间参考统一', '转换至 CGCS2000 / 3°分带', '已完成', 'done')}${prepRow('03', '空间范围裁剪', '按武汉市研究区边界裁剪', '已完成', 'done')}${prepRow('04', '空间尺度协调', '栅格重采样至 500 m 分辨率', '待处理', 'active')}${prepRow('05', '数据格式标准化', '输出统一 GeoPackage 数据集', '待处理', '')}
      <button class="primary-btn" data-action="preprocess">${icon('play')}执行待处理步骤</button></section>
      <section class="panel"><div class="panel-header"><div><span class="section-label">PREVIEW</span><h2>配准预览</h2></div></div><div class="alignment-preview"><div class="preview-map">${mapSvg()}</div><div class="preview-meta"><span>目标坐标系</span><strong>CGCS2000 / 3°分带</strong><span>统一分析单元</span><strong>500 m 网格</strong><span>研究区</span><strong>武汉市域 · 8,221 km²</strong></div></div></section></div>`;
}

function prepRow(number, title, note, status, stateClass) {
  return `<div class="prep-row ${stateClass}"><div class="prep-number">${stateClass === 'done' ? icon('check') : number}</div><div><strong>${title}</strong><small>${note}</small></div><span>${status}</span></div>`;
}

function resultsView() {
  return `${pageHeading('RESULTS & REPORT', '结果与报告', '查看全局评价、局部空间差异，并生成可复现的分析摘要。',
    `<button class="primary-btn" data-action="report">${icon('download')}生成报告</button>`)}
    <div class="result-summary"><div class="result-card"><span>全局相关系数</span><strong>0.82</strong><small class="good">显著正相关 · p &lt; 0.01</small></div><div class="result-card"><span>局部 R² 均值</span><strong>0.74</strong><small class="good">较全局提升 9.2%</small></div><div class="result-card"><span>显著差异区域</span><strong>18.6%</strong><small class="warn">主要集中于江夏区</small></div><div class="result-card"><span>模型运行耗时</span><strong>02:41</strong><small>12,486 个空间单元</small></div></div>
    <section class="panel report-panel"><div class="panel-header"><div><span class="section-label">ANALYSIS LOG</span><h2>分析报告摘要</h2></div><span class="tag teal">可导出</span></div><div class="report-content"><h3>异源同质空间数据精细尺度交叉验证</h3><p>本次分析以人口密度与夜光遥感强度为主要变量，采用自适应双平方核进行局部空间建模。结果显示，两类数据在武汉中心城区具有较高空间一致性，在江夏区、东西湖区边缘存在明显局部差异。</p><div class="report-grid"><div><span>分析对象</span><strong>人口 · 夜光 · 几何</strong></div><div><span>带宽策略</span><strong>自适应带宽 0.62</strong></div><div><span>空间权重</span><strong>双平方核</strong></div><div><span>输出时间</span><strong>2026-09-11 14:32</strong></div></div></div></section>`;
}

function settingsView() {
  return `${pageHeading('SYSTEM SETTINGS', '系统设置', '管理工作台显示、结果输出和本地项目偏好。')}
    <section class="panel settings-panel"><div class="setting-line"><div><strong>自动保存分析参数</strong><small>每次调整模型参数后保存当前配置</small></div><label class="switch"><input type="checkbox" checked><span></span></label></div><div class="setting-line"><div><strong>显示实验性图层</strong><small>允许在地图中显示局部误差和样本密度</small></div><label class="switch"><input type="checkbox"><span></span></label></div><div class="setting-line"><div><strong>报告默认格式</strong><small>导出时使用结构化 Markdown 摘要</small></div><select><option>Markdown</option><option>CSV + Markdown</option></select></div><div class="setting-line"><div><strong>项目目录</strong><small>/projects/wuhan-2026</small></div><button class="outline-btn">更改目录</button></div></section>`;
}

function bindEvents() {
  document.querySelectorAll('[data-view]').forEach((element) => element.addEventListener('click', () => {
    state.activeView = element.dataset.view;
    render();
  }));
  document.querySelectorAll('[data-action]').forEach((element) => element.addEventListener('click', () => handleAction(element.dataset.action)));
  document.querySelectorAll('[data-chart]').forEach((element) => element.addEventListener('click', () => {
    state.chartMode = element.dataset.chart;
    render();
  }));
  document.querySelectorAll('[data-point]').forEach((element) => element.addEventListener('click', () => {
    state.selectedPoint = Number(element.dataset.point);
    render();
  }));
  const xMetric = document.querySelector('#xMetric');
  const yMetric = document.querySelector('#yMetric');
  if (xMetric) xMetric.addEventListener('change', (event) => { state.xMetric = event.target.value; render(); });
  if (yMetric) yMetric.addEventListener('change', (event) => { state.yMetric = event.target.value; render(); });
  const bandwidth = document.querySelector('#bandwidth');
  if (bandwidth) bandwidth.addEventListener('input', (event) => {
    state.bandwidth = Number(event.target.value);
    const output = document.querySelector('#bandwidthValue');
    if (output) output.textContent = state.bandwidth.toFixed(2);
  });
  document.querySelectorAll('[data-bandwidth-mode]').forEach((element) => element.addEventListener('click', () => {
    state.kernel = element.dataset.bandwidthMode;
    render();
  }));
  document.querySelectorAll('input[data-layer]').forEach((element) => element.addEventListener('change', (event) => {
    const key = event.target.dataset.layer;
    if (key === 'people') state.showPopulation = event.target.checked;
    if (key === 'night') state.showNight = event.target.checked;
    if (key === 'geometry') state.showGeometry = event.target.checked;
  }));
}

function handleAction(action) {
  if (action === 'run') {
    state.running = true;
    state.toast = '正在运行 GWR 局部模型…';
    render();
    setTimeout(() => { state.running = false; state.toast = '分析完成，已更新局部差异结果'; render(); }, 1400);
  } else if (action === 'upload') {
    state.toast = '演示模式：可接入 CSV、GeoTIFF、GeoPackage 数据源';
    render();
  } else if (action === 'export' || action === 'report') {
    const report = `空间数据交叉验证报告\\n生成时间：2026-09-11\\n\\n全局相关系数：0.82\\n局部R²均值：0.74\\n显著差异区域：18.6%\\n带宽策略：${state.kernel} ${state.bandwidth.toFixed(2)}\\n`;
    const blob = new Blob([report], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = '空间数据交叉验证报告.txt'; link.click();
    URL.revokeObjectURL(url);
    state.toast = '报告已导出';
    render();
  } else if (action === 'preprocess') {
    state.toast = '预处理任务已加入队列';
    render();
  } else if (action === 'reset') {
    state.selectedPoint = 18; state.bandwidth = 0.62; state.xMetric = 'people'; state.yMetric = 'night';
    render();
  } else if (action === 'zoom-in' || action === 'zoom-out') {
    state.toast = action === 'zoom-in' ? '已放大地图视图' : '已缩小地图视图';
    render();
  }
}

function render() {
  document.querySelector('#app').innerHTML = appTemplate();
  bindEvents();
}

render();
