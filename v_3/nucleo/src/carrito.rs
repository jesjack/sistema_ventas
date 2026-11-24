//! Reglas del carrito, iguales a `v_2/table_modules/carrito.py`.
//!
//! - Una entrada sin producto, sin precio o sin cantidad (vacío o cero) no se agrega.
//! - Si el producto y el precio ya están en el carrito, se suman las cantidades; si no, fila nueva.
//!   La comparación del producto es exacta (la v2 trata "Blusa" y "blusa" como distintos).

use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct FilaCarrito {
    pub producto: String,
    pub precio: f64,
    pub cantidad: i64,
    pub subtotal: f64,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Carrito {
    pub filas: Vec<FilaCarrito>,
}

impl Carrito {
    pub fn nuevo() -> Self {
        Self::default()
    }

    /// Agrega una entrada. Devuelve `false` (y no cambia nada) si falta algún dato.
    pub fn agregar(&mut self, producto: &str, precio: f64, cantidad: i64) -> bool {
        if producto.is_empty() || precio == 0.0 || cantidad == 0 {
            return false;
        }
        match self.filas.iter_mut().find(|f| f.producto == producto && f.precio == precio) {
            Some(fila) => {
                fila.cantidad += cantidad;
                fila.subtotal = precio * fila.cantidad as f64;
            }
            None => self.filas.push(FilaCarrito {
                producto: producto.to_string(),
                precio,
                cantidad,
                subtotal: precio * cantidad as f64,
            }),
        }
        true
    }

    /// Quita la fila `indice` (si existe).
    pub fn quitar(&mut self, indice: usize) {
        if indice < self.filas.len() {
            self.filas.remove(indice);
        }
    }

    pub fn vaciar(&mut self) {
        self.filas.clear();
    }

    pub fn esta_vacio(&self) -> bool {
        self.filas.is_empty()
    }

    /// Suma de los subtotales (`total_del_carrito` de la v2).
    pub fn total(&self) -> f64 {
        self.filas.iter().map(|f| f.subtotal).sum()
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn quitar_y_vaciar() {
        let mut c = Carrito::nuevo();
        c.agregar("blusa", 150.0, 1);
        c.agregar("faja", 200.0, 1);
        c.quitar(0);
        assert_eq!(c.filas.len(), 1);
        assert_eq!(c.filas[0].producto, "faja");
        c.quitar(7); // fuera de rango: nada
        c.vaciar();
        assert!(c.esta_vacio());
        assert_eq!(c.total(), 0.0);
    }
}
