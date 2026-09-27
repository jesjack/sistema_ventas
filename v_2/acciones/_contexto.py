import functools


def usar_contexto(ejecutar):
    """OBSOLETO: solo lo usa acciones/ver_camaras.py (la app de cámaras la mantiene otra instancia).
    Las acciones nuevas reciben un nucleo.contexto.Contexto y usan `ctx.atributo` con imports explícitos.
    Cuando ver_camaras deje de usarlo, borrar este archivo y Contexto.keys/__getitem__.

    Antes de correr ejecutar(ctx), copia cada entrada de ctx como global de
    este modulo, para escribir "cart" en vez de "ctx["cart"]" en el cuerpo.

    Limite real: esto copia valores HACIA el modulo de la accion, no los
    sincroniza de vuelta. Sirve para leer del contexto y para llamar metodos
    que mutan un objeto compartido (cart.clear(), sheet_admin.temporary_unlock()).
    Si una accion necesita REASIGNAR algo que main.py debe seguir viendo (ej.
    la bandera "selling"), eso todavia requiere escribir ctx["selling"] = ...
    de forma explicita -- una reasignacion normal solo cambiaria el global de
    este modulo, no el de main.py.
    """

    @functools.wraps(ejecutar)
    def envoltura(ctx):
        ejecutar.__globals__.update(ctx)
        return ejecutar(ctx)

    return envoltura
