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

## 项目结构

```text
Hydro-Vegetation-Analysis/
├── LICENSE
├── README.md
├── boundary/
│   └── gadm41_CHN_0.shp
├── config.yaml
├── data/
│   ├── processed/
│   │   └── ERA5Land/
│   └── raw/
│       └── ERA5Land/
├── environment.yml
├── figures/
├── outputs/
├── scripts/
│   ├── era5-land_download.py
│   └── preprocess.py
└── utils.py
```

---

## 环境配置

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

## 下载 ERA5-Land 数据

### ERA5-Land 数据下载配置（Windows）
本项目使用 `cdsapi` 调用 **Copernicus Climate Data Store (CDS)** API 自动下载 ERA5-Land 再分析数据。

在运行下载脚本之前，需要完成 CDS API 认证配置。

---

### 1. 注册 Copernicus CDS 账号

访问：
https://cds.climate.copernicus.eu/
注册账号并登录。

登录后进入：

```
My profile → API key
```

获取个人 API 信息。

API 信息格式如下：

```
url: https://cds.climate.copernicus.eu/api
key: 123456:abcdefg-xxxx-xxxx
```

---

### 2. 创建 `.cdsapirc` 文件

`cdsapi` 会自动读取用户目录下的 `.cdsapirc` 文件。

Windows 文件路径：

```
C:\Users\你的用户名\.cdsapirc
```

例如：

```
C:\Users\ZhangSan\.cdsapirc
```

---

### 3. 创建配置文件

打开 **记事本（Notepad）**，输入以下内容：

```yaml
url: https://cds.climate.copernicus.eu/api
key: YOUR-UID:YOUR-API-KEY
```

将：

```
YOUR-UID
YOUR-API-KEY
```

替换为 CDS 页面提供的信息。

示例：

```yaml
url: https://cds.climate.copernicus.eu/api
key: 123456:abcdefg-xxxx-xxxx
```

注意：

- `url` 和 `key` 之间使用冒号 `:`
- 不需要添加引号
- 不要多加空格
- API key 不要提交到 GitHub

---

### 4. 保存 `.cdsapirc`

选择：

```
文件 → 另存为
```

设置：

文件名：

```
.cdsapirc
```

保存类型：

```
所有文件 (*.*)
```

编码：

```
UTF-8
```

保存位置：

```
C:\Users\你的用户名\
```

最终文件结构：

```
C:
└── Users
    └── 你的用户名
        └── .cdsapirc
```

---

### 5. 检查文件是否创建成功

打开 Windows 命令提示符：

```cmd
cd %USERPROFILE%
```

查看文件：

```cmd
dir /a
```

如果配置成功，可以看到：

```
.cdsapirc
```

---

### 6. 测试 CDS API 配置

进入项目环境：

```bash
conda activate data-analysis
```

启动 Python：

```bash
python
```

输入：

```python
import cdsapi

client = cdsapi.Client()
```

如果配置正确，不会出现认证错误。

退出：

```python
exit()
```

---

### 7. 安装 cdsapi（如果缺少）

如果运行脚本出现：

```
ModuleNotFoundError: No module named 'cdsapi'
```

请确认进入项目环境：

```bash
conda activate data-analysis
```

安装：

```bash
conda install -c conda-forge cdsapi
```

或者：

```bash
pip install cdsapi
```

---

### 8. 开始下载 ERA5-Land 数据

确认：

1. 已创建 `.cdsapirc`
2. 已激活项目环境
3. 已安装 cdsapi

运行：

```bash
python scripts/era5-land_download.py
```

下载的数据默认保存到：

```
data/raw/ERA5Land/
```

下载参数（年份、变量、区域等）统一在 `config.yaml` 中配置。

**不要直接修改 Python 脚本中的参数。**

---

## config.yaml

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

## 数据目录说明

### data/raw/

保存下载得到的原始数据。

原则：

- 原始数据只下载，不修改。
- 后续所有处理均基于其副本。

---

### data/processed/

保存预处理后的数据，例如：

- 单位统一
- 缺失值处理
- 中国边界裁剪
- 重投影
- 重采样

---

### outputs/

保存分析结果，例如：

- 趋势图
- 显著性结果
- Moran's I
- LISA
- 表格

---

### figures/

保存论文和汇报所使用的图片。

---

## 工作流程

建议按照下面顺序完成数据处理：

1. 下载 ERA5-Land 数据。
2. 对数据进行预处理。
3. 进行趋势分析。
4. 进行空间统计分析。
5. 绘制结果图。

---

## Git 使用规范

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

## 注意事项

1. 所有脚本均在项目根目录运行。
2. 下载参数统一通过 `config.yaml` 配置。
3. 不要直接修改原始数据。
4. 每完成一个功能，及时提交 Git。
5. 提交前确保代码能够正常运行。

---

## 联系方式

王勇哲
河海大学水文水资源学院
YongzheWong@Outlook.com

**如遇到代码或数据处理问题，请及时在组内沟通，不要直接修改他人负责的代码模块。**