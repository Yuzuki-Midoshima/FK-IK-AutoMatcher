# FK-IK AutoMatcher

Autodesk Maya 2026向けのFK/IKポーズマッチツールです。リグ内のノードを1つ選択すると構成を解析し、FKとIKの姿勢を双方向に合わせます。

## 機能

- FK → IK：IKコントローラーとポールベクターを配置
- IK → FK：IKジョイントの回転をFKコントローラーへ反映
- Manifest、命名規則、階層からリグを自動解析
- 手動設定とJSON形式での保存・読込
- 1回のMaya Undoで操作全体を取り消し

## 対応環境

- Autodesk Maya 2026
- Python 3.11 / PySide6

## 起動

リポジトリを任意の場所へ配置し、MayaのPythonシェルフから実行します。

```python
import runpy
runpy.run_path(r"D:\tools\FK-IK-AutoMatcher\launch_fk_ik_auto_matcher.py")
```

または、リポジトリのルートをPythonパスへ追加して起動できます。

```python
import sys

sys.path.insert(0, r"D:\tools\FK-IK-AutoMatcher")
from fk_ik_auto_matcher import show
show()
```

## 使い方

1. FK/IKリグ内のノードを1つ選択
2. 「選択を設定」でリグを解析
3. 必要に応じて詳細設定を調整
4. FK → IK、またはIK → FKを実行

自動判定できないリグは、各ノードを手動指定してJSONへ保存できます。

## テスト

```bash
python -m unittest discover -s tests -v
```

基本対象は始点・中間・終点からなる3点チェーンです。ストレッチや独自の行列ネットワークなど、リグ固有機能の同期には対応していません。

## ライセンス

[MIT License](LICENSE)
