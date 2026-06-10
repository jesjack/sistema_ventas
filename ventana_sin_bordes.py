import tkinter as tk


def main() -> None:
    root = tk.Tk()
    root.title("Overlay")

    # Quita bordes y barra de titulo.
    root.overrideredirect(True)

    # Mantiene la ventana por encima de las demas.
    root.attributes("-topmost", True)

    root.geometry("360x140+80+80")
    root.configure(bg="#1f2937")

    container = tk.Frame(root, bg="#1f2937", padx=16, pady=14)
    container.pack(fill="both", expand=True)

    label = tk.Label(
        container,
        text="Ventana sin bordes\nSiempre al frente",
        bg="#1f2937",
        fg="#f9fafb",
        font=("Helvetica", 13, "bold"),
        justify="center",
    )
    label.pack(expand=True)

    hint = tk.Label(
        container,
        text="Ventana fija | Esc para cerrar",
        bg="#1f2937",
        fg="#d1d5db",
        font=("Helvetica", 10),
    )
    hint.pack()

    root.bind("<Escape>", lambda _event: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
