import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Set

import requests
from bs4 import BeautifulSoup

# Страница станции из задания (всё тот же tutu)
STATION_URL = "https://www.tutu.ru/station.php?nnst=45807&date=all"

# Ключевые слова для дней следования и типы поездов
DAY_LABELS = ("ежедневно", "будни", "выходные")
TRAIN_KINDS = ("Электричка", "Спутник", "Иволга", "Ласточка")


@dataclass(frozen=True)
class Train:
    """Модель одного рейса электрички в удобном виде."""

    time: str   # время отправления, например "08:45"
    route: str  # строка вида "Москва Ярославская — Сергиев Посад"
    days: str   # тип дней следования: "ежедневно", "будни" и т.п.


def download_html(url: str = STATION_URL) -> str:
    """Скачивает HTML-страницу расписания с tutu.ru."""
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    # Tutu может отдавать разные кодировки — опираемся на apparent_encoding
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def load_html_from_file(path: Path) -> str:
    """Читает HTML из локального файла."""
    return path.read_text(encoding="utf-8")


def normalize_spaces(text: str) -> str:
    """Заменяет повторяющиеся пробелы одним и подрезает края."""
    return re.sub(r"\s+", " ", text).strip()


def remove_train_kind(text: str) -> str:
    """Убирает из начала строки тип поезда (Электричка, Спутник и т.д.)."""
    for kind in TRAIN_KINDS:
        if text.startswith(kind):
            return text[len(kind):].lstrip()
    return text


def remove_day_labels(text: str) -> str:
    """Убирает слова про дни следования (ежедневно, будни, выходные)."""
    result = text
    for label in DAY_LABELS:
        result = re.sub(label, "", result, flags=re.IGNORECASE)
    return result


def simplify_route_text(raw: str) -> str:
    """
    Приводит строку маршрута к аккуратному виду:
    - обрезает комментарии в скобках;
    - убирает тип поезда;
    - убирает указание дней;
    - убирает номер поезда в конце;
    - схлопывает пробелы.
    """
    # убираем всё, что в круглых скобках (например "(обычно путь 1-6)")
    route = raw.split("(", 1)[0]

    route = route.strip()
    route = remove_train_kind(route)
    route = remove_day_labels(route)

    # убираем номер поезда в конце (цифры + возможный пробел)
    route = re.sub(r"\d+\s*$", "", route)

    route = normalize_spaces(route)
    # немного подчистим краевые запятые и лишние пробелы
    return route.strip(" ,")


def find_departure_time(chunks: Iterable[str]) -> Optional[str]:
    """Ищет время формата HH:MM в наборе текстов ячейки/строки."""
    for part in chunks:
        match = re.search(r"\b\d{2}:\d{2}\b", part)
        if match:
            return match.group(0)
    return None


def find_days_label(chunks: Iterable[str]) -> str:
    """Определяет тип дней следования по ключевым словам."""
    for part in chunks:
        lowered = part.lower()
        for label in DAY_LABELS:
            if label in lowered:
                return label
    return ""


def find_route_string(chunks: Iterable[str]) -> Optional[str]:
    """
    Ищет строку с маршрутом — первую, в которой есть тире/дефис между станциями,
    и приводит её к аккуратному виду.
    """
    for part in chunks:
        if "—" in part or "–" in part or "-" in part:
            route = simplify_route_text(part)
            if route:
                return route
    return None


def parse_schedule(html: str, day_filter: Optional[str] = None) -> List[Train]:
    """
    Разбирает HTML расписания и возвращает список рейсов.

    day_filter:
      - None  -> не фильтровать по дням;
      - "будни" или "ежедневно" -> оставить только соответствующие рейсы.
    """
    soup = BeautifulSoup(html, "lxml")
    rows = soup.find_all("tr")

    result: List[Train] = []
    seen: Set[Tuple[str, str, str]] = set()  # защита от дублей

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        texts = [
            normalize_spaces(cell.get_text(" ", strip=True))
            for cell in cells
            if cell.get_text(strip=True)
        ]
        if not texts:
            continue

        time = find_departure_time(texts)
        if not time:
            continue

        days = find_days_label(texts)
        if day_filter and days != day_filter:
            # фильтрация по типу дней, если указана
            continue

        route = find_route_string(texts)
        if not route:
            continue

        key = (time, route, days)
        if key in seen:
            continue
        seen.add(key)

        result.append(Train(time=time, route=route, days=days))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Парсер расписания электричек с tutu.ru "
            "для станции https://www.tutu.ru/station.php?nnst=45807"
        )
    )
    parser.add_argument(
        "--days",
        choices=["будни", "ежедневно"],
        help="Фильтр по типу дней (будни / ежедневно). Если не указан — показать все рейсы.",
    )
    parser.add_argument(
        "--file",
        type=str,
        help=(
            "Путь к локальному HTML-файлу со страницей tutu.ru. "
            "Если не указан, страница будет скачана с сайта."
        ),
    )
    parser.add_argument(
        "--output",
        type=str,
        default="schedule.json",
        help="Имя JSON-файла для сохранения результата (по умолчанию schedule.json).",
    )

    # parse_known_args — чтобы не падать в средах, где добавляют свои аргументы (например, Jupyter/Colab)
    args, _ = parser.parse_known_args()

    if args.file:
        html = load_html_from_file(Path(args.file))
    else:
        html = download_html()

    schedule = parse_schedule(html, day_filter=args.days)

    # Выводим список рейсов в консоль
    for trip in schedule:
        print(f"{trip.time} | {trip.route} | {trip.days}")

    # Сохраняем в JSON
    output_path = Path(args.output)
    data = [asdict(t) for t in schedule]
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
