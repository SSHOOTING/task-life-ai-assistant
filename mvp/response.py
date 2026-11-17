from __future__ import annotations


KIND_LABELS = {
    "task": "任务",
    "daily_task": "每日任务",
    "task_progress": "任务进展",
}


def compose_receipt(tasks: list[dict], clarification: str | None = None) -> str:
    if clarification:
        return clarification
    if not tasks:
        return "原话已保存，暂未生成任务。"
    labels: list[str] = []
    for task in tasks:
        label = KIND_LABELS.get(task["kind"], task["kind"])
        title = task.get("title") or task.get("content") or ""
        labels.append(f"{label}：{title}")
    return "已记下：" + "；".join(labels) + "。原话已按原文保存。"

