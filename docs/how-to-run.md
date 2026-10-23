# Как запускать самому (шпаргалка для Акеля)

Все команды — в терминале в папке `C:\00_Workspace\02_player` (PowerShell или терминал VS Code).

## 0. Один раз: копия игры
Бот работает только с **копией** игры в `game_lab\game`, Steam-оригинал не трогаем. Копия уже есть.
Если её нет (новый компьютер, обновление игры):
```
Copy-Item -Recurse "C:\Program Files (x86)\Steam\steamapps\common\Buckshot Roulette\Buckshot Roulette_windows" game_lab\game
```
Сохранения игры сначала забэкапь: `%APPDATA%\Godot\app_userdata\Buckshot Roulette` → `game_lab\save_backup_<дата>`.
После обновления игры через Steam мост может перестать работать (поменялись имена в коде) — тогда зови меня.

## 1. ИИ играет сам (режим play)
```
python -m player.buckshot.launch --agent runs/d3.1/dqn_100000.pt --mode play --speed 10 --pause 0.3
```
- Запускает копию игры, ждёт мост, открывает оверлей. Дальше всё само: меню → таблетки (Double or
  Nothing) → двери → подпись «b» → игра. После смерти начинает новую партию.
- `--speed` — скорость игры (1 = обычная, 10 = в 10 раз быстрее). `--pause` — сколько секунд держать
  «мысль» на экране перед ходом (для просмотра на ×1 ставь 1.5).
- Мышку и клавиатуру в игре лучше не трогать: клик по столу может помешать боту.
- **F8** — подробная панель (все ходы с оценками, предметы). **F10** — закрыть оверлей (игра остаётся).
- Закрыть игру — Alt+F4 в её окне.

## 2. Ты играешь, ИИ подсказывает (режим hint)
```
python -m player.buckshot.launch --agent runs/d3.1/dqn_100000.pt
```
Сам дойди до Double or Nothing. Слева — патроны и что ты знаешь, справа — совет и его оценка.
Партия с подсказками тоже сохраняется (бот в таблице: `akel (hints …)`).

Какую модель взять: любой файл `runs/<версия>/dqn_<партий>.pt`. Сейчас лучшая — `runs/d3.1/dqn_100000.pt`.
Старые версии — в `runs/archive/`.

## 3. Посмотреть, как сыграл
```
python -m player.buckshot.livecheck        # последняя сессия: правильно ли ИИ видел стол, какие ходы выбирал
python -m player.report                    # все обучения + партии на настоящей игре (таблица внизу)
```
Файлы: `reports/games.csv` — каждая партия; `reports/live_thoughts/*.jsonl` — каждая мысль на игре.

## 4. Обучить новую версию (без игры, в симуляторе)
```
python -m player.buckshot.train --games 100000 --run d4 --items --agent dqn --shaping hp_events_items
python -m tensorboard.main --logdir runs     # живые графики: открой http://127.0.0.1:6006
```
Награды (`--shaping`): `none`, `hp_potential`, `hp_speed` (d3), `hp_events` (d2.1), `hp_events_items` (d3.1).
`--seed 1` — другой случайный старт (чтобы проверить, что результат не везение).

## 5. Разобрать версию и нарисовать отчёты
```
python -m player.buckshot.replay runs/d4/dqn_100000.pt     # логи партий + тактики + ошибки
python -m player.buckshot.viz compare d3.1 d4               # картинки сравнения в reports/
python -m player.buckshot.viz curves                        # кривые обучения
python -m player.buckshot.viz network runs/d4/dqn_100000.pt # картинка нейросети
```

## Если что-то не так
- «the bridge didn't answer» — игра не открылась или в `game_lab\game` нет `override.cfg`
  (launch сам его копирует; файл-исходник: `player\buckshot\bridge\override.cfg`).
- Бот застрял на одном месте — закрой оверлей (F10) и запусти `launch` снова: он подключится к уже
  открытой игре.
- Оверлей не виден поверх игры — игра в эксклюзивном полноэкранном режиме; оверлей сам переключает
  её в полноэкранный без рамки, если не помогло — в настройках игры включи оконный режим.
