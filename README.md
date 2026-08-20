# Maya FK/IK Auto Matcher

A reusable FK/IK pose-matching tool for **Autodesk Maya 2026 / Python 3**.

FK/IK切り替え時に発生するポーズのずれを抑え、IKへの切り替えではPole Vectorも自動的に再配置するマッチングツールです。

キャラクター **Diana** 用に制作したFK/IK Match Toolをベースに、キャラクター固有の命名やリグ構造への依存を減らし、異なる3点リムでも利用できるよう再設計しました。

汎用化では単純にノード名を設定へ移すのではなく、**対象リグの解決、設定の検証、Pole Vectorのフォールバック**まで含めてワークフローを見直しています。

---

## Features

* FK → IK / IK → FKの双方向マッチング
* 3点リムに対応
* IK End Controlの位置・回転を自動調整
* Pole Vectorの自動計算・再配置
* 選択ノードを起点としたリグ構造の解決
* Rig Module Builder Manifestからのリグ情報取得
* Manifestがない場合のScene Search
* Match Settingsの確認・編集
* 設定のJSON保存・再利用
* 直線に近いリムに対するPole Vector Fallback
* Missing / Ambiguous Nodeの検出
* Expected Node Typeの検証
* 1操作を1つのMaya Undo Chunkとして処理
* Maya非依存のPole Vector計算をpytestでテスト

---

## Why I Made This

最初のFK/IK Match Toolは、Dianaの腕リグ専用として制作しました。

Diana版では対象となるJoint、Control、FKIK Switchがすべて既知だったため、

```text
Known Diana Rig
      ↓
Match Controls
      ↓
Switch FK / IK
```

というシンプルな処理で実装できます。

しかし、別のリグへ適用する場合は、

* ノード名
* Namespace
* Joint / Control構造
* FKIK Switch
* Pole Vectorの状態

などが異なります。

そこで汎用版では、マッチング処理の前に**「現在選択されているリグを解決する工程」**を追加しました。

```text
Selected Node
      ↓
Resolve Rig
      ↓
Validate Settings
      ↓
Match Controls
      ↓
Switch FK / IK
```

これにより、マッチングロジックとキャラクター固有の情報を分離しています。

---

# Workflow

ツールの基本フローは以下です。

```text
Select Rig Node
      │
      ▼
  Rig Resolver
      │
      ▼
Manifest Available?
   │           │
  YES          NO
   │           │
   ▼           ▼
Manifest     Scene
  Data       Search
   │           │
   └─────┬─────┘
         ▼
   Match Settings
         │
         ▼
      Validate
         │
         ▼
    FK ↔ IK Match
```

Diana版では直接マッチングを開始していましたが、汎用版では**Resolve → Validate → Match**の3段階に分けています。

---

# Rig Resolution

## Manifest Resolution

Rig Module Builderによって生成されたリグでは、`rigModuleBuilderManifest` に保存された情報を優先して使用します。

```text
Selected Node
      ↓
Find Manifest
      ↓
Read Explicit Rig Data
      ↓
Build Match Settings
```

名前からリグ構造を推測するのではなく、生成時に記録された情報から対象ノードを取得することで、より明示的にリグを解決できます。

---

## Scene Resolution

Manifestが存在しない場合は、選択されたノードを起点としてシーン内から候補を検索します。

```text
Selected Node
      ↓
Read Context
      ↓
Namespace / Side / Limb
      ↓
Search Candidates
      ↓
Validate
      ↓
Match Settings
```

候補が存在しない場合や、一意に特定できない場合は、不確実なノードを操作せずエラーとして停止します。

---

# Match Settings

Resolverによって取得したリグ情報はMatch Settingsとしてまとめます。

主に以下の情報を保持します。

* FK Start / Mid / End Controls
* IK Start / Mid / End Joints
* IK End Control
* Pole Vector Control
* FKIK Switch
* FK / IK Switch Values
* Pole Vector Settings

自動解析した結果は確認・修正でき、JSONとして保存して同じリグで再利用できます。

```text
Auto Resolve
      ↓
Match Settings
      ↓
Check / Edit
      ↓
Save JSON
      ↓
Reuse
```

自動解析だけに依存せず、必要に応じて人が修正できる構成にしています。

---

# FK → IK

FKからIKへ切り替える場合は、現在のリムのポーズを基準にIK側を合わせます。

```text
Current FK Pose
      ↓
Match IK End Control
      ↓
Calculate Pole Vector
      ↓
Move Pole Control
      ↓
Switch to IK
```

まずIK End ControlのTransformを現在のEnd Jointへ合わせます。

その後、Start / Mid / End JointからPole Vector位置を計算し、Pole Controlを移動します。

すべてのマッチングが完了した後にFKIK SwitchをIKへ変更します。

### Why Match Before Switch?

単純にFKIK Switchだけを変更すると、切り替え先のControlが現在のポーズと一致していないため、ポーズが変化する可能性があります。

```text
Switch First

FK Pose
   ↓
Switch
   ↓
Different IK Transform
   ↓
Pose Pop
```

そのため、

```text
Match First

FK Pose
   ↓
Match IK Controls
   ↓
Switch
   ↓
Maintain Pose
```

の順番で処理します。

---

# IK → FK

IKからFKへ切り替える場合は、現在のIK Chainを基準にFK Controlsを合わせます。

```text
Current IK Pose
      ↓
Match FK Start
      ↓
Match FK Mid
      ↓
Match FK End
      ↓
Switch to FK
```

Start → Mid → Endの順番で対応するFK Controlを現在のJoint Poseへ合わせます。

すべてのマッチングが完了してからFKへ切り替えます。

---

# Pole Vector Calculation

通常の状態では、3点のJoint位置から現在の曲げ方向を計算します。

```text
Start -------- Projection -------- End
                     \
                      \
                      Mid
                       ↑
                  Bend Direction
```

Mid JointをStart → Endの直線へ射影し、

```text
BendVector = Mid - Projection
```

からリムの曲げ方向を取得します。

正規化した方向をMid Jointから延長することでPole Vectorの基本位置を求めます。

```text
PolePosition =
    Mid
    + BendDirection × Distance
```

---

# Straight Limb Fallback

3点が完全、またはほぼ一直線の場合、Joint位置だけでは曲げ方向を一意に判断できません。

```text
Start -------- Mid -------- End

Bend Direction = Undefined
```

異なるリグやポーズでも使用できるよう、Pole Vector方向を決定するためのフォールバックを追加しています。

```text
Joint Geometry
      ↓
Stable Direction?
   ┌──────┴──────┐
  YES            NO
   ↓              ↓
 Use          Current Pole
Direction       Direction
                  ↓
                Valid?
             ┌────┴────┐
            YES        NO
             ↓          ↓
            Use     Preferred
                     Angle
```

## 1. Joint Geometry

まずStart / Mid / Endの位置から通常の曲げ方向を計算します。

安定した方向が取得できる場合は、その結果を使用します。

## 2. Current Pole Direction

Jointがほぼ直線の場合、現在のPole Vector Controlの位置を利用します。

既存のPoleがどちら側に配置されていたかを方向情報として利用することで、現在のリグ状態をできるだけ維持します。

## 3. Preferred Angle

Current Poleからも安定した方向を取得できない場合は、Jointの `preferredAngle` を利用してフォールバック方向を求めます。

これにより、直線に近いリムでも可能な限り予測可能なマッチングを行います。

---

# Error Handling

汎用化によって対象となるリグ構造が固定ではなくなるため、誤ったノードを操作しないことを重視しています。

以下のような状態を検出します。

* Required Nodeが存在しない
* 同名候補が複数存在する
* Expected Node Typeと一致しない
* Match Settingsが不完全
* FKIK Switchへ書き込めない
* Pole Vector方向を安全に決定できない

不確実な状態では処理を継続せず、問題の内容をエラーとして表示します。

また、1回のマッチング処理は1つのMaya Undo Chunkとして実行します。

---

# Architecture

汎用版では、Diana固有の実装から発展させる際に責務を分離しました。

```text
        UI
        │
        ▼
     Resolver
        │
        ▼
   Match Settings
        │
        ▼
      Matcher
        │
        ▼
   Math / Maya API
```

### UI

ユーザー操作、設定表示、Match実行を担当します。

### Resolver

選択されたノードやManifestから対象リグを解決します。

### Match Settings

ResolverとMatcherの間で、マッチングに必要なリグ情報を保持します。

### Matcher

解決済みのリグ情報を使用してFK → IK / IK → FK処理を実行します。

### Math

Pole Vectorなどの数学処理を担当します。

Maya Sceneへ直接依存しない計算を分離することで、Mayaを起動せずpytestから検証できるようにしています。

---

# From Diana-specific to General-purpose

汎用版は、Diana版のノード名だけを変更したものではありません。

```text
Diana-specific FK/IK Matcher
             │
             ▼
 Separate Rig-specific Data
             │
             ▼
       Rig Resolver
             │
             ▼
    Editable Settings
             │
             ▼
 Pole Vector Fallback
             │
             ▼
General-purpose FK/IK Auto Matcher
```

|                 | Diana Version              | General-purpose                           |
| --------------- | -------------------------- | ----------------------------------------- |
| Target          | Diana Arm                  | 3-point Limb                              |
| Rig Structure   | Known                      | Resolved                                  |
| Node Resolution | Fixed                      | Resolver                                  |
| Manifest        | Not Required               | Supported                                 |
| Settings        | Diana-specific             | Editable / JSON                           |
| Straight Limb   | Stop                       | Fallback                                  |
| Pole Direction  | Joint Geometry             | Geometry / Current Pole / Preferred Angle |
| Goal            | Predictable Diana Workflow | Reusability                               |

Diana版では、対象リグが既知であることを利用し、**シンプルで予測可能な処理**を優先しました。

汎用版では対象リグが未知であることを前提として、

**「どのリグを操作するかを解決する」
→「安全に操作できるか検証する」
→「マッチングする」**

というワークフローへ変更しています。

---

# Installation

CloneまたはDownloadしたRepositoryの `src` をPython Pathへ追加します。

MayaのPython Script Editor：

```python
import sys
import importlib

project_src = r"C:\path\to\FK-IK-AutoMatcher\src"

if project_src not in sys.path:
    sys.path.insert(0, project_src)

import fkik_match_tool.launcher
importlib.reload(fkik_match_tool.launcher)

fkik_match_tool.launcher.show()
```

または `src/fkik_match_tool` をMayaのユーザー `scripts` ディレクトリへ配置し、

```python
from fkik_match_tool.launcher import show
show()
```

で起動します。

---

# Development

```shell
python -m pip install -e .
python -m pytest
```

Pole Vector計算などのMaya非依存ロジックはMaya外でテストできます。

Scene IntegrationについてはMaya 2026上で実際のリグを使用して確認します。

---

# Limitations

* 現在は3点リムを対象としています
* リグ構造によってはMatch Settingsの手動調整が必要です
* Locked Channelや特殊なConstraint / Offset構造では追加対応が必要になる場合があります
* Controlが要求されたTransformを受け取れることを前提としています
* 独自性の高いリグではResolverによる完全な自動判定ができない場合があります
* Maya Scene Fileは誤公開防止のためRepositoryでは除外しています

---

# Environment

* Autodesk Maya 2026
* Python 3
* Maya Python API
* PySide
* pytest

---

# License

MIT License

© 2026 Yuzuki Midoshima
