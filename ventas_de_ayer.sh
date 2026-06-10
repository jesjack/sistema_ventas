#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="${1:-$SCRIPT_DIR/ventas.db}"
FECHA_AYER="$(date -d 'yesterday' +%F)"

if [[ ! -f "$DB" ]]; then
	echo "No se encontró la base de datos: $DB" >&2
	exit 1
fi

python3 - "$DB" "$FECHA_AYER" <<'PY'
import sqlite3
import sys
import tkinter as tk
from tkinter import ttk


db_path = sys.argv[1]
fecha_ayer = sys.argv[2]

con = sqlite3.connect(db_path)
cur = con.cursor()

cur.execute(
	"""
	SELECT
		v.id,
		v.hora,
		i.producto,
		i.cantidad,
		i.precio
	FROM ventas v
	JOIN venta_items i ON i.venta_id = v.id
	WHERE v.fecha = ?
	ORDER BY v.hora ASC, v.id ASC, i.id ASC
	""",
	(fecha_ayer,),
)
ventas = cur.fetchall()
con.close()

ventas_por_id = {}
orden_ventas = []
for venta_id, hora, producto, cantidad, precio in ventas:
	if venta_id not in ventas_por_id:
		ventas_por_id[venta_id] = []
		orden_ventas.append(venta_id)
	total = float(cantidad) * float(precio)
	ventas_por_id[venta_id].append((hora, producto, cantidad, precio, total))


def money(value):
	return f"$ {float(value):.2f}"


total_general = sum(float(venta[3]) * float(venta[4]) for venta in ventas)

root = tk.Tk()
root.title("Ventas de ayer")
root.geometry("940x560")
root.minsize(640, 240)
root.configure(bg="white")

style = ttk.Style(root)
try:
	style.theme_use("clam")
except tk.TclError:
	pass

style.configure(
	"Treeview",
	background="white",
	fieldbackground="white",
	foreground="black",
	borderwidth=0,
	relief="flat",
	padding=0,
	rowheight=28,
	bordercolor="white",
	lightcolor="white",
	darkcolor="white",
)
style.configure(
	"Treeview.Heading",
	background="#1f2937",
	foreground="white",
	relief="flat",
)
style.map(
	"Treeview",
	background=[("selected", "#e5e7eb")],
	foreground=[("selected", "black")],
)

header = tk.Frame(root, bg="white", padx=18, pady=14)
header.pack(fill="x")

tk.Label(
	header,
	text="Ventas de ayer",
	bg="white",
	fg="black",
	font=("Helvetica", 18, "bold"),
).pack(anchor="w")

tk.Label(
	header,
	text=f"Fecha: {fecha_ayer}    Base: {db_path}    Cierra con Esc",
	bg="white",
	fg="black",
	font=("Helvetica", 10),
).pack(anchor="w", pady=(4, 0))

body = tk.Frame(root, bg="white", padx=18, pady=8)
body.pack(fill="both", expand=True)
body.rowconfigure(0, weight=1)
body.columnconfigure(0, weight=1)

columns = ("id", "hora", "producto", "cantidad", "precio", "total")
tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="none")
tree.configure(height=max(3, min(len(ventas) + 1, 14)))

headings = {
	"id": "Id",
	"hora": "Hora",
	"producto": "Producto",
	"cantidad": "Cantidad",
	"precio": "Precio",
	"total": "Total",
}

widths = {
	"id": 90,
	"hora": 130,
	"producto": 330,
	"cantidad": 120,
	"precio": 120,
	"total": 140,
}

for column in columns:
	tree.heading(column, text=headings[column])
	anchor = "w" if column == "producto" else "center"
	tree.column(column, width=widths[column], anchor=anchor, stretch=True)

tree.bind("<Button-1>", lambda _event: "break")
tree.bind("<ButtonRelease-1>", lambda _event: "break")
tree.bind("<Key>", lambda _event: "break")

sale_colors = ("#ffffff", "#f3f4f6")
sale_tags = {}

for index, venta_id in enumerate(orden_ventas):
	tag_name = f"sale_{venta_id}"
	sale_tags[venta_id] = tag_name
	tree.tag_configure(tag_name, background=sale_colors[index % len(sale_colors)], foreground="black")

tree.tag_configure("total_row", background="#1f2937", foreground="white")
tree.tag_configure("empty_row", background="#f3f4f6", foreground="black")

if ventas:
	for venta_id in orden_ventas:
		for hora, producto, cantidad, precio, total in ventas_por_id[venta_id]:
			tree.insert(
				"",
				"end",
				values=(venta_id, hora, producto, cantidad, money(precio), money(total)),
				tags=(sale_tags[venta_id],),
			)
else:
	tree.insert("", "end", values=("-", "-", "No hubo ventas ayer", "", "", ""), tags=("empty_row",))


def actualizar_scrollbar(first, last):
	scrollbar.set(first, last)
	if float(first) <= 0.0 and float(last) >= 1.0:
		scrollbar.grid_remove()
	else:
		scrollbar.grid()


scrollbar = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
tree.configure(yscrollcommand=actualizar_scrollbar)

tree.grid(row=0, column=0, sticky="nsew")
scrollbar.grid(row=0, column=1, sticky="ns")
actualizar_scrollbar("0.0", "1.0")

tree.insert("", "end", values=("", "", "", "", "TOTAL DEL DIA", money(total_general)), tags=("total_row",))

root.update_idletasks()
content_width = body.winfo_reqwidth() + 36
content_height = header.winfo_reqheight() + body.winfo_reqheight() + 24
root.geometry(f"{max(content_width, 640)}x{max(content_height, 240)}")

root.bind("<Escape>", lambda _event: root.destroy())
root.mainloop()
PY
