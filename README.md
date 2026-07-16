# Hydro-Vegetation-Analysis

## 项目简介

本项目用于研究 **2000—2025 年中国植被变化对水资源可利用量的影响**。

主要工作包括：

- 下载 ERA5-Land 气象与水文数据；
- 数据预处理（质量控制、异常值处理、重采样、裁剪等）；
- 趋势分析（Theil-Sen、M-K 检验、滑动 T 检验）；
- 空间统计分析（Moran's I、LISA）；
- 结果可视化。

---

# 项目结构

```text
Hydro-Vegetation-Analysis/
│
├── config.yaml               # 项目配置文件
├── environment.yml           # Conda 环境
├── README.md
├── LICENSE
│
├── data/
│   ├── raw/                  # 原始数据
│   │   └── ERA5Land/
│   ├── processed/            # 预处理后的数据
│   └── boundary/             # 中国边界数据
│
├── figures/                  # 图片输出
├── outputs/                  # 分析结果
│
├── scripts/
│   ├── era5-land_download.py # ERA5-Land 下载
│   ├── preprocess.py         # 数据预处理
│   ├── trend_analysis.py     # 趋势分析
│   └── spatial_analysis.py   # 空间统计分析
│
└── .gitignore                # 避免提交到git
```

---

# 环境配置

第一次使用项目时，创建 Conda 环境：

```bash
conda env create -f environment.yml
```

激活环境：

```bash
conda activate data-analysis
```

如果环境已经存在，则直接激活即可。

---

# 下载 ERA5-Land 数据

下载脚本位于：

```text
scripts/era5-land_download.py
```

在项目根目录运行：

```bash
python scripts/era5-land_download.py
```

下载参数（年份、变量、区域等）统一在 `config.yaml` 中配置。

**不要直接修改 Python 脚本中的参数。**

---

# config.yaml

项目所有配置均放在 `config.yaml` 中，包括：

- 下载年份
- 数据路径
- 下载变量
- 中国区域范围
- 重采样参数
- 投影参数
- 趋势分析参数
- 空间统计参数

修改实验设置时，请优先修改 `config.yaml`。

---

# 数据目录说明

## data/raw/

保存下载得到的原始数据。

原则：

- 原始数据只下载，不修改。
- 后续所有处理均基于其副本。

---

## data/processed/

保存预处理后的数据，例如：

- 单位统一
- 缺失值处理
- 中国边界裁剪
- 重投影
- 重采样

---

## outputs/

保存分析结果，例如：

- 趋势图
- 显著性结果
- Moran's I
- LISA
- 表格

---

## figures/

保存论文和汇报所使用的图片。

---

# 工作流程

建议按照下面顺序完成数据处理：

1. 下载 ERA5-Land 数据。
2. 对数据进行预处理。
3. 进行趋势分析。
4. 进行空间统计分析。
5. 绘制结果图。

---

# Git 使用规范

提交代码前请先：

```bash
git pull
```

完成修改后：

```bash
git add .
git commit -m "描述本次修改"
git push
```

不要提交以下内容：

- 大型数据文件（如 `.nc`）
- Python 缓存文件
- Conda 环境文件
- 临时输出文件

这些内容已在 `.gitignore` 中进行了忽略。

关于git更详细的教程可参考*ProGit 2nd Edition*或自行查阅相关资料。

---

# 注意事项

1. 所有脚本均在项目根目录运行。
2. 下载参数统一通过 `config.yaml` 配置。
3. 不要直接修改原始数据。
4. 每完成一个功能，及时提交 Git。
5. 提交前确保代码能够正常运行。

---

# 联系方式

王勇哲
河海大学水文水资源学院
YongzheWong@Outlook.com

**如遇到代码或数据处理问题，请及时在组内沟通，不要直接修改他人负责的代码模块。**