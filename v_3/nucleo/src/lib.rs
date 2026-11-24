//! Núcleo de la caja V3: las reglas de negocio y el acceso a `ventas.db`, sin interfaz.
//!
//! Por D18 (`v_3/docs/repaso_decisiones_sin_calc.md`), este crate no sabe nada de Tauri ni de la
//! vista web: se prueba con `cargo test` y la app lo usa a través de comandos.
//!
//! **Compatibilidad con la v2:** mientras la v2 siga en producción, la base y su esquema son de
//! ella. Este núcleo lee y escribe las mismas tablas con las mismas reglas, y NO migra nada
//! (`base::verificar_esquema` solo comprueba). Las pruebas de `tests/contra_v2.rs` comparan con
//! resultados generados ejecutando el código real de la v2 (`pruebas_v2/generar_casos.py`).

pub mod base;
pub mod botones;
pub mod caja;
pub mod carrito;
pub mod catalogo;
pub mod cobro;
pub mod corte;
pub mod esquema;
pub mod importar;
pub mod sesiones;
pub mod ventas;

#[cfg(test)]
mod contra_v2;

pub use base::{Base, ErrorBase};
pub use carrito::{Carrito, FilaCarrito};
pub use catalogo::{CodigoBarras, ErrorCatalogo, Producto};
pub use cobro::{Cobro, ErrorCobro, leer_monto};
pub use sesiones::DatosUsuario;
pub use ventas::{FilaVentas, Momento};
