"""
ui/styles.py
============
Constante de stil partajate între widget-urile UI.
Importate în fiecare ui/*.py care are nevoie de butoane stilizate.
"""

BTN_PRIMARY = """
    QPushButton {
        background-color: #3498db; color: white;
        border-radius: 10px; padding: 10px;
    }
    QPushButton:hover { background-color: #2980b9; }
"""
BTN_SUCCESS = """
    QPushButton {
        background-color: #27ae60; color: white;
        border-radius: 10px; padding: 10px;
    }
    QPushButton:hover { background-color: #229954; }
"""
BTN_WARNING = """
    QPushButton {
        background-color: #f39c12; color: white;
        border-radius: 10px; padding: 10px;
    }
    QPushButton:hover { background-color: #e67e22; }
"""
BTN_DANGER = """
    QPushButton {
        background-color: #e74c3c; color: white;
        border-radius: 10px; padding: 10px;
    }
    QPushButton:hover { background-color: #c0392b; }
"""
