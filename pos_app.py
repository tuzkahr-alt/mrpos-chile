# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║  MRPOS Chile - Sistema Punto de Venta Local                  ║
║  Diseñado para Minimarkets, Botillerías, Farmacias           ║
║  Con integración Balanza Digi SM-100                         ║
╚══════════════════════════════════════════════════════════════╝
Ejecutar: python pos_app.py
Acceso local: http://localhost:5000
Acceso remoto: http://0.0.0.0:5000 (para Ngrok/Cloudflare)
"""

import os, json, csv, io
from datetime import datetime, date
from flask import Flask, request, jsonify, render_template_string, Response
from flask_sqlalchemy import SQLAlchemy

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════
app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Usar PostgreSQL persistente si existe la variable DATABASE_URL (Render), de lo contrario usa SQLite Local
database_url = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(BASE_DIR, "pos_system.db")}')
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JSON_AS_ASCII'] = False
db = SQLAlchemy(app)

# ══════════════════════════════════════════════════════════════
# MODELOS DE BASE DE DATOS
# ══════════════════════════════════════════════════════════════
class Negocio(db.Model):
    __tablename__ = 'negocios'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(50), default='')
    direccion = db.Column(db.String(200), default='')
    rut = db.Column(db.String(20), default='')
    logo_url = db.Column(db.String(300), default='')
    admin_pin = db.Column(db.String(20), default='1234')
    activo = db.Column(db.Boolean, default=True)

class Producto(db.Model):
    __tablename__ = 'productos'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    sku = db.Column(db.String(20), nullable=False)
    codigo_barra = db.Column(db.String(20), default='')
    nombre = db.Column(db.String(100), nullable=False)
    # Precios
    precio = db.Column(db.Float, nullable=False, default=0)        # Precio venta c/IVA
    precio_costo = db.Column(db.Float, default=0)                  # Costo neto
    precio_oferta = db.Column(db.Float, default=0)                 # Precio unitario en oferta
    oferta_desde = db.Column(db.Integer, default=0)                # Cant. mínima para oferta (0=no)
    precio_pack = db.Column(db.Float, default=0)                   # Precio del pack
    cantidad_pack = db.Column(db.Integer, default=0)               # Unidades que trae el pack (0=no)
    # Stock
    stock = db.Column(db.Float, nullable=False, default=0)
    stock_minimo = db.Column(db.Float, default=5)                  # Stock crítico
    # Clasificación
    tipo_producto = db.Column(db.String(20), default='normal')     # normal | pesable | unidad
    es_pesable = db.Column(db.Boolean, default=False)
    categoria = db.Column(db.String(50), default='General')
    activo = db.Column(db.Boolean, default=True)
    imagen_url = db.Column(db.String(300), default='')
    creado = db.Column(db.DateTime, default=datetime.utcnow)

class Promocion(db.Model):
    __tablename__ = 'promociones'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    nombre = db.Column(db.String(100), nullable=False)
    precio_promo = db.Column(db.Float, nullable=False)
    activo = db.Column(db.Boolean, default=True)
    productos = db.relationship('PromoProducto', backref='promo', lazy=True)

class PromoProducto(db.Model):
    __tablename__ = 'promo_producto'
    id = db.Column(db.Integer, primary_key=True)
    promo_id = db.Column(db.Integer, db.ForeignKey('promociones.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    cantidad = db.Column(db.Integer, default=1)


class Venta(db.Model):
    __tablename__ = 'ventas'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    cajero_id = db.Column(db.Integer, db.ForeignKey('cajero.id'), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    subtotal = db.Column(db.Float, default=0)
    descuento = db.Column(db.Float, default=0)
    total = db.Column(db.Float, nullable=False)
    metodo_pago = db.Column(db.String(20), default='Efectivo')
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    monto_pagado = db.Column(db.Float, default=0)
    vuelto = db.Column(db.Float, default=0)
    detalles = db.relationship('DetalleVenta', backref='venta', lazy=True)

class DetalleVenta(db.Model):
    __tablename__ = 'detalle_venta'
    id = db.Column(db.Integer, primary_key=True)
    venta_id = db.Column(db.Integer, db.ForeignKey('ventas.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    cantidad = db.Column(db.Float, nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False)
    descuento = db.Column(db.Float, default=0)
    subtotal = db.Column(db.Float, nullable=False)

class CierreCaja(db.Model):
    __tablename__ = 'cierre_caja'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    total_efectivo = db.Column(db.Float, default=0)
    total_debito = db.Column(db.Float, default=0)
    total_credito = db.Column(db.Float, default=0)
    total_fiado = db.Column(db.Float, default=0)
    total_general = db.Column(db.Float, default=0)
    num_ventas = db.Column(db.Integer, default=0)

class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    nombre = db.Column(db.String(100), nullable=False)
    rut = db.Column(db.String(15), default='')
    telefono = db.Column(db.String(20), default='')
    email = db.Column(db.String(100), default='')
    direccion = db.Column(db.String(200), default='')
    saldo_pendiente = db.Column(db.Float, default=0)
    activo = db.Column(db.Boolean, default=True)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

class MovimientoCuenta(db.Model):
    __tablename__ = 'movimiento_cuenta'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    tipo = db.Column(db.String(10))
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(200), default='')
    venta_id = db.Column(db.Integer, db.ForeignKey('ventas.id'), nullable=True)

class Cajero(db.Model):
    __tablename__ = 'cajero'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    nombre = db.Column(db.String(100), nullable=False)
    rut = db.Column(db.String(20), default='')
    pin = db.Column(db.String(4), nullable=False)
    turno = db.Column(db.String(50), default='Mañana')
    activo = db.Column(db.Boolean, default=True)
    rol = db.Column(db.String(20), default='cajero')

class Historial(db.Model):
    __tablename__ = 'historial'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    usuario_id = db.Column(db.Integer, nullable=True)
    usuario_nombre = db.Column(db.String(100), default='Admin')
    accion = db.Column(db.String(50)) # CREAR, EDITAR, ELIMINAR, STOCK, LOGIN
    modulo = db.Column(db.String(50)) # PRODUCTOS, VENTAS, CAJA, etc
    descripcion = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

def registrar_log(nid, uid, unom, accion, modulo, desc):
    try:
        log = Historial(negocio_id=nid, usuario_id=uid, usuario_nombre=unom, accion=accion, modulo=modulo, descripcion=desc)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"Error registrando log: {e}")

class Proveedor(db.Model):
    __tablename__ = 'proveedores'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    nombre = db.Column(db.String(100), nullable=False)
    rut = db.Column(db.String(20), default='')
    telefono = db.Column(db.String(20), default='')
    activo = db.Column(db.Boolean, default=True)

class FacturaCompra(db.Model):
    __tablename__ = 'factura_compra'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores.id'), nullable=False)
    numero_factura = db.Column(db.String(50), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    monto_total = db.Column(db.Float, nullable=False)

class Categoria(db.Model):
    __tablename__ = 'categorias'
    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey('negocios.id'), nullable=False, default=1)
    nombre = db.Column(db.String(50), nullable=False)

# ══════════════════════════════════════════════════════════════
# LÓGICA BALANZA DIGI SM-100
# ══════════════════════════════════════════════════════════════
def procesar_codigo_balanza(codigo_ean13):
    """
    Procesa códigos EAN-13 generados por la balanza Digi SM-100.
    
    FORMATO DEL CÓDIGO EAN-13 DE LA BALANZA:
    ┌──┬─────────┬───────────┬──┐
    │24│  SKU    │ PESO/PRECIO│CD│
    │2 │ 5 díg  │  5 díg     │1 │
    └──┴─────────┴───────────┴──┘
    
    Posiciones (0-indexed):
    - [0:2]  = '24' → Prefijo que identifica producto pesable
    - [2:7]  = SKU del producto (5 dígitos)
    - [7:12] = Peso en gramos O Precio (5 dígitos)
    - [12]   = Dígito de control
    
    Ejemplo: 2400123001500 → SKU=00123, Peso=1.500 kg (o $1500)
    """
    codigo = str(codigo_ean13).strip()
    if len(codigo) == 13 and codigo[:2] == '24':
        sku_balanza = codigo[2:7]       # Dígitos 2 al 6 → SKU
        valor_raw = codigo[7:12]        # Dígitos 7 al 11 → peso/precio
        valor = int(valor_raw)
        peso_kg = valor / 1000.0        # Convertir gramos a kg
        return {
            'es_balanza': True,
            'sku': sku_balanza,
            'valor_raw': valor,
            'peso_kg': peso_kg,
            'precio_directo': valor      # Algunos usan precio directo
        }
    return {'es_balanza': False}

# ══════════════════════════════════════════════════════════════
# RUTAS API
# ══════════════════════════════════════════════════════════════

# ── PRODUCTOS ──
@app.route('/api/productos', methods=['GET'])
def get_productos():
    nid = request.args.get('negocio_id', 1)
    productos = Producto.query.filter_by(negocio_id=nid, activo=True).all()
    return jsonify([{
        'id': p.id, 'sku': p.sku, 'codigo_barra': p.codigo_barra,
        'nombre': p.nombre, 'precio': p.precio, 'precio_costo': getattr(p, 'precio_costo', 0),
        'stock': p.stock, 'stock_minimo': p.stock_minimo,
        'tipo_producto': getattr(p, 'tipo_producto', 'normal'), 'es_pesable': p.es_pesable,
        'categoria': p.categoria, 'imagen_url': p.imagen_url,
        'precio_oferta': getattr(p, 'precio_oferta', 0), 'oferta_desde': getattr(p, 'oferta_desde', 0),
        'precio_pack': getattr(p, 'precio_pack', 0), 'cantidad_pack': getattr(p, 'cantidad_pack', 0),
        'margen': round(((p.precio - getattr(p,'precio_costo',0)) / p.precio * 100), 1) if p.precio else 0
    } for p in productos])

@app.route('/api/productos', methods=['POST'])
def crear_producto():
    d = request.json
    tipo = d.get('tipo_producto', 'normal')
    p = Producto(
        negocio_id=d.get('negocio_id', 1),
        sku=d['sku'], nombre=d['nombre'],
        precio=float(d.get('precio', 0)),
        stock=float(d.get('stock', 0)),
        stock_minimo=float(d.get('stock_minimo', 5)),
        es_pesable=(tipo == 'pesable'),
        codigo_barra=d.get('codigo_barra', ''),
        categoria=d.get('categoria', 'General'),
        imagen_url=d.get('imagen_url', '')
    )
    # Nuevos campos opcionales
    for attr, val in [
        ('precio_costo', float(d.get('precio_costo', 0))),
        ('tipo_producto', tipo),
        ('precio_oferta', float(d.get('precio_oferta', 0))),
        ('oferta_desde', int(d.get('oferta_desde', 0))),
        ('precio_pack', float(d.get('precio_pack', 0))),
        ('cantidad_pack', int(d.get('cantidad_pack', 0))),
    ]:
        if hasattr(p, attr):
            setattr(p, attr, val)
    db.session.add(p)
    db.session.commit()
    registrar_log(p.negocio_id, d.get('usuario_id'), d.get('usuario_nombre', 'Admin'), 'CREAR', 'PRODUCTOS', f"Creó {p.nombre} ({p.sku})")
    return jsonify({'ok': True, 'id': p.id})

@app.route('/api/productos/<int:pid>', methods=['PUT'])
def editar_producto(pid):
    p = Producto.query.get_or_404(pid)
    d = request.json
    floats = ['precio', 'precio_costo', 'stock', 'stock_minimo', 'precio_oferta', 'precio_pack']
    ints   = ['oferta_desde', 'cantidad_pack']
    strs   = ['nombre', 'codigo_barra', 'categoria', 'sku', 'imagen_url', 'tipo_producto']
    for k in floats:
        if k in d and hasattr(p, k): setattr(p, k, float(d[k]))
    for k in ints:
        if k in d and hasattr(p, k): setattr(p, k, int(d[k]))
    for k in strs:
        if k in d and hasattr(p, k): setattr(p, k, d[k])
    if 'tipo_producto' in d:
        p.es_pesable = (d['tipo_producto'] == 'pesable')
    db.session.commit()
    registrar_log(p.negocio_id, d.get('usuario_id'), d.get('usuario_nombre', 'Admin'), 'EDITAR', 'PRODUCTOS', f"Modificó {p.nombre}")
    return jsonify({'ok': True})

@app.route('/api/productos/<int:pid>', methods=['DELETE'])
def eliminar_producto(pid):
    p = Producto.query.get_or_404(pid)
    uid = request.args.get('uid')
    unom = request.args.get('unom', 'Admin')
    p.activo = False
    db.session.commit()
    registrar_log(p.negocio_id, uid, unom, 'ELIMINAR', 'PRODUCTOS', f"Eliminó {p.nombre}")
    return jsonify({'ok': True})

@app.route('/api/historial', methods=['GET'])
def get_historial():
    nid = request.args.get('negocio_id', 1)
    logs = Historial.query.filter_by(negocio_id=nid).order_by(Historial.fecha.desc()).limit(100).all()
    return jsonify([{
        'fecha': l.fecha.strftime('%Y-%m-%d %H:%M:%S'), 'usuario': l.usuario_nombre,
        'accion': l.accion, 'modulo': l.modulo, 'desc': l.descripcion
    } for l in logs])

# ── IMPORTAR / EXPORTAR PRODUCTOS (CSV) ──
@app.route('/api/productos/exportar', methods=['GET'])
def exportar_productos():
    nid = request.args.get('negocio_id', 1)
    prods = Producto.query.filter_by(negocio_id=nid, activo=True).all()
    
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['sku', 'codigo_barra', 'nombre', 'categoria', 'precio', 'precio_costo', 'stock', 'stock_minimo', 'tipo_producto', 'precio_oferta', 'oferta_desde', 'precio_pack', 'cantidad_pack'])
    for p in prods:
        cw.writerow([p.sku, p.codigo_barra, p.nombre, p.categoria, p.precio, getattr(p,'precio_costo',0), p.stock, p.stock_minimo, getattr(p,'tipo_producto','normal'), getattr(p,'precio_oferta',0), getattr(p,'oferta_desde',0), getattr(p,'precio_pack',0), getattr(p,'cantidad_pack',0)])
    
    return Response(si.getvalue(), mimetype='text/csv', headers={"Content-disposition": f"attachment; filename=productos_negocio_{nid}.csv"})

@app.route('/api/productos/importar', methods=['POST'])
def importar_productos():
    nid = request.json.get('negocio_id', 1)
    uid = request.json.get('usuario_id')
    unom = request.json.get('usuario_nombre', 'Admin')
    csv_data = request.json.get('csv_text', '')
    
    if not csv_data: return jsonify({'ok': False, 'msg': 'Sin datos'})
    
    f = io.StringIO(csv_data)
    reader = csv.DictReader(f)
    cont = 0
    for row in reader:
        try:
            # Buscar si ya existe por SKU
            p = Producto.query.filter_by(negocio_id=nid, sku=row['sku']).first()
            if not p:
                p = Producto(negocio_id=nid, sku=row['sku'], nombre=row['nombre'], activo=True)
                db.session.add(p)
            
            p.nombre = row.get('nombre', p.nombre)
            p.codigo_barra = row.get('codigo_barra', p.codigo_barra)
            p.categoria = row.get('categoria', p.categoria)
            p.precio = float(row.get('precio', p.precio))
            p.precio_costo = float(row.get('precio_costo', getattr(p, 'precio_costo', 0)))
            p.stock = float(row.get('stock', p.stock))
            p.stock_minimo = float(row.get('stock_minimo', p.stock_minimo))
            p.tipo_producto = row.get('tipo_producto', getattr(p, 'tipo_producto', 'normal'))
            p.es_pesable = (p.tipo_producto == 'pesable')
            p.precio_oferta = float(row.get('precio_oferta', 0))
            p.oferta_desde = int(row.get('oferta_desde', 0))
            p.precio_pack = float(row.get('precio_pack', 0))
            p.cantidad_pack = int(row.get('cantidad_pack', 0))
            cont += 1
        except Exception as e:
            print(f"Error importando fila: {e}")
            continue
    
    db.session.commit()
    registrar_log(nid, uid, unom, 'IMPORTAR', 'PRODUCTOS', f"Importación masiva de {cont} productos vía CSV")
    return jsonify({'ok': True, 'count': cont})

@app.route('/api/backup', methods=['GET'])
def full_backup():
    nid = request.args.get('negocio_id', 1)
    prods = Producto.query.filter_by(negocio_id=nid).all()
    ventas = Venta.query.filter_by(negocio_id=nid).all()
    cls = Cliente.query.filter_by(negocio_id=nid).all()
    provs = Proveedor.query.filter_by(negocio_id=nid).all()
    
    backup = {
        'negocio_id': nid,
        'fecha': datetime.now().isoformat(),
        'productos': [{'sku':p.sku, 'nombre':p.nombre, 'precio':p.precio, 'stock':p.stock} for p in prods],
        'clientes': [{'nombre':c.nombre, 'rut':c.rut, 'saldo':c.saldo_pendiente} for c in cls],
        'proveedores': [{'nombre':p.nombre, 'rut':p.rut} for p in provs],
        'ventas': [{'id':v.id, 'total':v.total, 'fecha':v.fecha.isoformat()} for v in ventas]
    }
    
    si = io.StringIO()
    json.dump(backup, si, indent=2)
    return Response(si.getvalue(), mimetype='application/json', headers={"Content-disposition": f"attachment; filename=backup_mrpos_{nid}.json"})

# ── PROMOCIONES / COMBOS ──
@app.route('/api/promociones', methods=['GET'])
def get_promociones():
    nid = request.args.get('negocio_id', 1)
    promos = Promocion.query.filter_by(negocio_id=nid, activo=True).all()
    result = []
    for pr in promos:
        items = []
        for pp in pr.productos:
            prod = Producto.query.get(pp.producto_id)
            if prod:
                items.append({'producto_id': prod.id, 'nombre': prod.nombre, 'cantidad': pp.cantidad})
        result.append({'id': pr.id, 'nombre': pr.nombre, 'precio_promo': pr.precio_promo, 'productos': items})
    return jsonify(result)

@app.route('/api/promociones', methods=['POST'])
def crear_promocion():
    d = request.json
    pr = Promocion(negocio_id=d.get('negocio_id', 1), nombre=d['nombre'], precio_promo=float(d['precio_promo']))
    db.session.add(pr)
    db.session.flush()
    for item in d.get('productos', []):
        pp = PromoProducto(promo_id=pr.id, producto_id=int(item['producto_id']), cantidad=int(item.get('cantidad', 1)))
        db.session.add(pp)
    db.session.commit()
    return jsonify({'ok': True, 'id': pr.id})

@app.route('/api/promociones/<int:prid>', methods=['DELETE'])
def eliminar_promocion(prid):
    pr = Promocion.query.get_or_404(prid)
    pr.activo = False
    db.session.commit()
    return jsonify({'ok': True})


# ── BUSCAR POR CÓDIGO (Barras / Balanza) ──
@app.route('/api/buscar_codigo', methods=['POST'])
def buscar_codigo():
    d = request.json
    codigo = d.get('codigo', '').strip()
    nid = d.get('negocio_id', 1)
    info_balanza = procesar_codigo_balanza(codigo)
    if info_balanza['es_balanza']:
        prod = Producto.query.filter_by(negocio_id=nid, sku=info_balanza['sku'], activo=True).first()
        if prod:
            return jsonify({
                'encontrado': True, 'es_balanza': True,
                'producto': {'id': prod.id, 'sku': prod.sku, 'nombre': prod.nombre,
                             'precio': prod.precio, 'es_pesable': prod.es_pesable},
                'peso_kg': info_balanza['peso_kg'],
                'precio_calculado': round(prod.precio * info_balanza['peso_kg'], 0)
            })
        return jsonify({'encontrado': False, 'es_balanza': True, 'msg': f'SKU {info_balanza["sku"]} no encontrado'})
    # Búsqueda normal por código de barra o SKU
    prod = Producto.query.filter(
        Producto.negocio_id == nid,
        (Producto.codigo_barra == codigo) | (Producto.sku == codigo),
        Producto.activo == True
    ).first()
    if prod:
        return jsonify({
            'encontrado': True, 'es_balanza': False,
            'producto': {'id': prod.id, 'sku': prod.sku, 'nombre': prod.nombre,
                         'precio': prod.precio, 'stock': prod.stock, 'es_pesable': prod.es_pesable, 'imagen_url': prod.imagen_url}
        })
    return jsonify({'encontrado': False, 'es_balanza': False})

# ── VENTAS ──
@app.route('/api/ventas', methods=['POST'])
def crear_venta():
    d = request.json
    items = d.get('items', [])
    metodo = d.get('metodo_pago', 'Efectivo')
    cliente_id = d.get('cliente_id', None)
    nid = d.get('negocio_id', 1)
    monto_pagado = float(d.get('monto_pagado', 0))
    venta_subtotal = float(d.get('subtotal', 0))
    venta_descuento = float(d.get('descuento', 0))
    venta_total = float(d.get('total', 0))
    
    # Si no vienen calculados del front, los calculamos aquí
    if venta_total == 0:
        venta_subtotal = 0
        for item in items:
            p_u = float(item.get('precio_unitario', 0))
            cant = float(item.get('cantidad', 0))
            desc = float(item.get('descuento', 0))
            venta_subtotal += (p_u * cant) - desc
        venta_total = venta_subtotal - venta_descuento

    venta = Venta(negocio_id=nid, total=venta_total, subtotal=venta_subtotal, 
                  descuento=venta_descuento, metodo_pago=metodo, 
                  cliente_id=cliente_id, cajero_id=d.get('cajero_id'), 
                  monto_pagado=monto_pagado)
    db.session.add(venta)
    db.session.flush()
    
    detalles_resp = []
    total_acumulado = 0
    for item in items:
        prod = Producto.query.get(item['producto_id'])
        if not prod: continue
        cant = float(item['cantidad'])
        precio_u = float(item.get('precio_unitario', prod.precio))
        desc_item = float(item.get('descuento', 0))
        sub = round((cant * precio_u) - desc_item, 0)
        det = DetalleVenta(venta_id=venta.id, producto_id=prod.id,
                           cantidad=cant, precio_unitario=precio_u, 
                           descuento=desc_item, subtotal=sub)
        db.session.add(det)
        prod.stock = max(0, prod.stock - cant)
        total_acumulado += sub
        detalles_resp.append({'nombre': prod.nombre, 'cantidad': cant,
                              'precio_unitario': precio_u, 'descuento': desc_item, 'subtotal': sub})
    
    # Ajuste final de total si fue calculado dinámicamente
    if venta_total == 0:
        venta.total = total_acumulado
        venta.subtotal = total_acumulado
    
    vuelto = max(0, monto_pagado - venta.total) if metodo == 'Efectivo' else 0
    venta.vuelto = vuelto
    # Si es Fiado, registrar en cuenta del cliente
    if metodo == 'Fiado' and cliente_id:
        cli = Cliente.query.get(cliente_id)
        if cli:
            cli.saldo_pendiente += venta.total
            mov = MovimientoCuenta(negocio_id=nid, cliente_id=cli.id, tipo='cargo', 
                                   monto=venta.total, descripcion=f'Venta #{venta.id}', venta_id=venta.id)
            db.session.add(mov)
    db.session.commit()
    
    dte_tipo = str(d.get('dte_tipo', '0'))
    dte_url = None
    if dte_tipo in ['39', '33']:
        # SIMULACIÓN DTE (Boleta o Factura)
        # Aquí iría el POST a OpenFactura o SimpleDTE
        dte_url = f"/api/boleta_dummy/{venta.id}"

    registrar_log(nid, d.get('cajero_id'), d.get('nombre_cajero', 'Sistema'), 'VENTA', 'VENTAS', f"Venta #{venta.id} por {venta.total} ({metodo})")
    
    return jsonify({'ok': True, 'venta_id': venta.id, 'total': venta.total,
                    'vuelto': vuelto, 'metodo_pago': metodo,
                    'monto_pagado': monto_pagado, 'detalles': detalles_resp, 
                    'dte_url': dte_url})

@app.route('/api/boleta_dummy/<int:vid>', methods=['GET'])
def boleta_dummy(vid):
    v = Venta.query.get_or_404(vid)
    html = f'''
    <!DOCTYPE html>
    <html lang="es">
    <head><meta charset="UTF-8"><title>DTE Simulado</title></head>
    <body style="width: 300px; margin: 0 auto; font-family: monospace; text-align: center; padding:20px; color:#000;">
    <h2>MI NEGOCIO SPA</h2>
    <p>RUT: 76.543.210-K<br>GIRO: COMERCIO AL POR MENOR</p>
    <h3 style="border:2px solid #000; padding:5px;">BOLETA ELECTRÓNICA N° {vid * 1054}</h3>
    <hr style="border-top:1px dashed #000;">
    '''
    for d in v.detalles:
        prod_obj = Producto.query.get(d.producto_id)
        prod_nombre = prod_obj.nombre if prod_obj else "Desconocido"
        html += f"<div style='text-align: left; margin:0;'>{prod_nombre}</div>"
        html += f"<div style='text-align: right; margin:0; margin-bottom:5px;'>{int(d.cantidad)} x ${int(d.precio_unitario)} = ${int(d.subtotal)}</div>"
    
    html += f"<hr style='border-top:1px dashed #000;'><h2>TOTAL: ${int(v.total)}</h2>"
    html += "<p>TIMBRE ELECTRÓNICO SII<br>Resolución N° 80 del 2014<br>Verifique documento en sii.cl</p>"
    html += """<br><br><button onclick="window.print()" style="padding:10px; width:100%; border-radius:5px; background:#1565C0; color:white; border:none; cursor:pointer;" class="no-print">Imprimir DTE</button>"""
    html += """<style>@media print { .no-print { display: none; } }</style></body></html>"""
    return html

@app.route('/api/ventas/<int:vid>', methods=['GET'])
def get_venta(vid):
    v = Venta.query.get_or_404(vid)
    detalles = [{'nombre': d.producto.nombre, 'cantidad': d.cantidad,
                 'precio_unitario': d.precio_unitario, 'subtotal': d.subtotal}
                for d in v.detalles]
    return jsonify({'id': v.id, 'fecha': v.fecha.strftime('%Y-%m-%d %H:%M:%S'),
                    'total': v.total, 'metodo_pago': v.metodo_pago,
                    'monto_pagado': v.monto_pagado, 'vuelto': v.vuelto,
                    'detalles': detalles})

@app.route('/api/ventas_hoy', methods=['GET'])
def ventas_hoy():
    hoy = date.today()
    nid = request.args.get('negocio_id', 1)
    ventas = Venta.query.filter(Venta.negocio_id == nid, db.func.date(Venta.fecha) == hoy).all()
    total = sum(v.total for v in ventas)
    por_metodo = {}
    for v in ventas:
        por_metodo[v.metodo_pago] = por_metodo.get(v.metodo_pago, 0) + v.total
    return jsonify({
        'num_ventas': len(ventas), 'total': total,
        'por_metodo': por_metodo,
        'ventas': [{'id': v.id, 'total': v.total, 'metodo_pago': v.metodo_pago,
                     'fecha': v.fecha.strftime('%H:%M:%S')} for v in ventas]
    })

# ── CIERRE DE CAJA ──
@app.route('/api/cierre_caja', methods=['POST'])
def cierre_caja():
    hoy = date.today()
    d = request.json
    nid = d.get('negocio_id', 1)
    ventas = Venta.query.filter(Venta.negocio_id == nid, db.func.date(Venta.fecha) == hoy).all()
    t_ef = sum(v.total for v in ventas if v.metodo_pago == 'Efectivo')
    t_db = sum(v.total for v in ventas if v.metodo_pago == 'Debito')
    t_cr = sum(v.total for v in ventas if v.metodo_pago == 'Credito')
    t_fi = sum(v.total for v in ventas if v.metodo_pago == 'Fiado')
    cierre = CierreCaja(negocio_id=nid, total_efectivo=t_ef, total_debito=t_db, 
                        total_credito=t_cr, total_fiado=t_fi, 
                        total_general=t_ef+t_db+t_cr+t_fi, num_ventas=len(ventas))
    db.session.add(cierre)
    db.session.commit()
    return jsonify({
        'ok': True, 'cierre_id': cierre.id,
        'efectivo': t_ef, 'debito': t_db, 'credito': t_cr, 'fiado': t_fi,
        'total': t_ef+t_db+t_cr+t_fi, 'num_ventas': len(ventas)
    })

# ── DASHBOARD DATA ──
@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    hoy = date.today()
    nid = request.args.get('negocio_id', 1)
    ventas_hoy_q = Venta.query.filter(Venta.negocio_id == nid, db.func.date(Venta.fecha) == hoy).all()
    total_hoy = sum(v.total for v in ventas_hoy_q)
    bajo_stock = Producto.query.filter(Producto.negocio_id == nid, Producto.stock <= Producto.stock_minimo, Producto.activo == True).all()
    total_productos = Producto.query.filter_by(negocio_id=nid, activo=True).count()
    por_metodo = {}
    for v in ventas_hoy_q:
        por_metodo[v.metodo_pago] = por_metodo.get(v.metodo_pago, 0) + v.total
        
    return jsonify({
        'ventas_hoy': len(ventas_hoy_q), 'total_hoy': total_hoy,
        'total_productos': total_productos,
        'bajo_stock': [{'id': p.id, 'nombre': p.nombre, 'stock': p.stock, 'stock_minimo': p.stock_minimo} for p in bajo_stock],
        'ultimas_ventas': [{'id': v.id, 'total': v.total, 'metodo_pago': v.metodo_pago,
                            'hora': v.fecha.strftime('%H:%M')} for v in ventas_hoy_q[-10:]],
        'por_metodo': por_metodo
    })

# ── PRODUCTOS BAJO STOCK ──
@app.route('/api/alertas', methods=['GET'])
def alertas():
    nid = request.args.get('negocio_id', 1)
    bajo = Producto.query.filter(Producto.negocio_id == nid, Producto.stock <= Producto.stock_minimo, Producto.activo == True).all()
    return jsonify([{'id': p.id, 'nombre': p.nombre, 'stock': p.stock, 'stock_minimo': p.stock_minimo} for p in bajo])

# ── CLIENTES ──
@app.route('/api/clientes', methods=['GET'])
def get_clientes():
    nid = request.args.get('negocio_id', 1)
    clientes = Cliente.query.filter_by(negocio_id=nid, activo=True).all()
    return jsonify([{'id': c.id, 'nombre': c.nombre, 'rut': c.rut,
                     'telefono': c.telefono, 'email': c.email,
                     'direccion': c.direccion, 'saldo_pendiente': c.saldo_pendiente
    } for c in clientes])

@app.route('/api/clientes', methods=['POST'])
def crear_cliente():
    d = request.json
    c = Cliente(negocio_id=d.get('negocio_id', 1), nombre=d['nombre'], 
                rut=d.get('rut',''), telefono=d.get('telefono',''),
                email=d.get('email',''), direccion=d.get('direccion',''))
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'id': c.id})

@app.route('/api/clientes/<int:cid>', methods=['PUT'])
def editar_cliente(cid):
    c = Cliente.query.get_or_404(cid)
    d = request.json
    for k in ['nombre','rut','telefono','email','direccion']:
        if k in d: setattr(c, k, d[k])
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/clientes/<int:cid>', methods=['DELETE'])
def eliminar_cliente(cid):
    c = Cliente.query.get_or_404(cid)
    c.activo = False
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/clientes/<int:cid>/cuenta', methods=['GET'])
def cuenta_cliente(cid):
    c = Cliente.query.get_or_404(cid)
    movs = MovimientoCuenta.query.filter_by(cliente_id=cid).order_by(MovimientoCuenta.fecha.desc()).all()
    return jsonify({
        'cliente': {'id': c.id, 'nombre': c.nombre, 'saldo_pendiente': c.saldo_pendiente},
        'movimientos': [{'id': m.id, 'fecha': m.fecha.strftime('%Y-%m-%d %H:%M'),
                         'tipo': m.tipo, 'monto': m.monto, 'descripcion': m.descripcion
        } for m in movs]
    })

@app.route('/api/clientes/<int:cid>/abono', methods=['POST'])
def abono_cliente(cid):
    c = Cliente.query.get_or_404(cid)
    d = request.json
    monto = float(d['monto'])
    nid = d.get('negocio_id', 1)
    mov = MovimientoCuenta(negocio_id=nid, cliente_id=cid, tipo='abono', monto=monto,
                           descripcion=d.get('descripcion', 'Abono de cliente'))
    db.session.add(mov)
    c.saldo_pendiente = max(0, c.saldo_pendiente - monto)
    db.session.commit()
    return jsonify({'ok': True, 'saldo_pendiente': c.saldo_pendiente})

# ── INFORMES ──
@app.route('/api/informes/stock_categoria', methods=['GET'])
def informe_stock_categoria():
    nid = request.args.get('negocio_id', 1)
    productos = Producto.query.filter_by(negocio_id=nid, activo=True).all()
    cats = {}
    for p in productos:
        if p.categoria not in cats:
            cats[p.categoria] = {'categoria': p.categoria, 'total_productos': 0,
                                 'total_stock': 0, 'valor_inventario': 0, 'bajo_stock': 0}
        cats[p.categoria]['total_productos'] += 1
        cats[p.categoria]['total_stock'] += p.stock
        cats[p.categoria]['valor_inventario'] += p.stock * p.precio
        if p.stock <= p.stock_minimo:
            cats[p.categoria]['bajo_stock'] += 1
    return jsonify(list(cats.values()))

@app.route('/api/informes/ventas_resumen', methods=['GET'])
def informe_ventas_resumen():
    hoy = date.today()
    nid = request.args.get('negocio_id', 1)
    ventas_hoy = Venta.query.filter(Venta.negocio_id == nid, db.func.date(Venta.fecha) == hoy).all()
    todas = Venta.query.filter_by(negocio_id=nid).all()
    por_metodo_hoy = {}
    for v in ventas_hoy:
        por_metodo_hoy[v.metodo_pago] = por_metodo_hoy.get(v.metodo_pago, 0) + v.total
    return jsonify({
        'hoy': {'num_ventas': len(ventas_hoy), 'total': sum(v.total for v in ventas_hoy), 'por_metodo': por_metodo_hoy},
        'historico': {'num_ventas': len(todas), 'total': sum(v.total for v in todas)}
    })

# ── DESCARGA DE INFORMES (CSV) ──
@app.route('/api/descargar/<tipo>', methods=['GET'])
def descargar_csv(tipo):
    si = io.StringIO()
    cw = csv.writer(si)
    if tipo == 'clientes':
        clientes = Cliente.query.filter_by(activo=True).all()
        cw.writerow(['ID', 'Nombre', 'RUT', 'Telefono', 'Email', 'Direccion', 'Deuda'])
        for c in clientes: cw.writerow([c.id, c.nombre, c.rut, c.telefono, c.email, c.direccion, c.saldo_pendiente])
    elif tipo == 'productos':
        productos = Producto.query.filter_by(activo=True).all()
        cw.writerow(['SKU', 'Nombre', 'Categoria', 'Precio', 'Stock'])
        for p in productos: cw.writerow([p.sku, p.nombre, p.categoria, p.precio, p.stock])
    elif tipo == 'categorias':
        nid = request.args.get('negocio_id', 1)
        productos = Producto.query.filter_by(negocio_id=nid, activo=True).all()
        cats = {}
        for p in productos:
            if p.categoria not in cats: cats[p.categoria] = {'p':0,'s':0,'v':0}
            cats[p.categoria]['p'] += 1
            cats[p.categoria]['s'] += p.stock
            cats[p.categoria]['v'] += p.stock * p.precio
        cw.writerow(['Categoria', 'Total Productos', 'Stock Total', 'Valor Inventario'])
        for c, d in cats.items(): cw.writerow([c, d['p'], round(d['s'],2), round(d['v'],0)])
    else:
        return "Tipo no válido", 400
    
    return Response(si.getvalue().encode('utf-8-sig'), mimetype="text/csv", headers={"Content-disposition": f"attachment; filename={tipo}.csv"})

# ── PROVEEDORES Y FACTURAS ──
@app.route('/api/proveedores', methods=['GET'])
def get_proveedores():
    nid = request.args.get('negocio_id', 1)
    provs = Proveedor.query.filter_by(negocio_id=nid, activo=True).all()
    return jsonify([{'id': p.id, 'nombre': p.nombre, 'rut': p.rut, 'telefono': p.telefono} for p in provs])

@app.route('/api/proveedores', methods=['POST'])
def add_proveedor():
    d = request.json
    p = Proveedor(negocio_id=d.get('negocio_id', 1), nombre=d['nombre'], rut=d.get('rut',''), telefono=d.get('telefono',''))
    db.session.add(p)
    db.session.commit()
    return jsonify({'ok': True, 'id': p.id})

@app.route('/api/facturas', methods=['GET'])
def get_facturas():
    nid = request.args.get('negocio_id', 1)
    facts = FacturaCompra.query.filter_by(negocio_id=nid).order_by(FacturaCompra.fecha.desc()).all()
    res = []
    for f in facts:
        prov = Proveedor.query.get(f.proveedor_id)
        res.append({'id': f.id, 'numero_factura': f.numero_factura, 'fecha': f.fecha.strftime('%d/%m/%Y'), 'monto_total': f.monto_total, 'proveedor': prov.nombre if prov else 'Desconocido'})
    return jsonify(res)

@app.route('/api/facturas', methods=['POST'])
def add_factura():
    d = request.json
    f = FacturaCompra(negocio_id=d.get('negocio_id', 1), proveedor_id=d['proveedor_id'], numero_factura=d['numero_factura'], monto_total=float(d['monto_total']))
    db.session.add(f)
    db.session.commit()
    return jsonify({'ok': True, 'id': f.id})

# ── CAJEROS ──
@app.route('/api/cajeros', methods=['GET'])
def get_cajeros():
    nid = request.args.get('negocio_id', 1)
    cajeros = Cajero.query.filter_by(negocio_id=nid, activo=True).all()
    return jsonify([{'id': c.id, 'nombre': c.nombre, 'rut': c.rut, 'turno': c.turno, 'rol': getattr(c, 'rol', 'cajero')} for c in cajeros])

@app.route('/api/cajeros/<int:cid>', methods=['PUT'])
def editar_cajero(cid):
    c = Cajero.query.get_or_404(cid)
    d = request.json
    for k in ['nombre', 'rut', 'pin', 'turno', 'rol']:
        if k in d: setattr(c, k, d[k])
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/cajeros/<int:cid>/stats', methods=['GET'])
def get_cajero_stats(cid):
    ventas = Venta.query.filter_by(cajero_id=cid).all()
    total = sum([v.total for v in ventas])
    count = len(ventas)
    return jsonify({'total_vendido': total, 'numero_ventas': count})

@app.route('/api/cajeros', methods=['POST'])
def add_cajero():
    d = request.json
    c = Cajero(negocio_id=d.get('negocio_id', 1), nombre=d['nombre'], 
               rut=d.get('rut',''), pin=d['pin'], turno=d.get('turno','Mañana'))
    if 'rol' in d: c.rol = d['rol']
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'id': c.id})

@app.route('/api/cajeros/<int:cid>', methods=['DELETE'])
def eliminar_cajero(cid):
    c = Cajero.query.get_or_404(cid)
    c.activo = False
    db.session.commit()
    return jsonify({'ok': True})

# ── CATEGORIAS ──
@app.route('/api/categorias', methods=['GET'])
def get_categorias():
    nid = request.args.get('negocio_id', 1)
    cats = Categoria.query.filter_by(negocio_id=nid).all()
    return jsonify([{'id': c.id, 'nombre': c.nombre} for c in cats])

@app.route('/api/categorias', methods=['POST'])
def add_categoria():
    d = request.json
    nid = d.get('negocio_id', 1)
    if not d.get('nombre'): return jsonify({'ok': False, 'msg': 'Nombre requerido'}), 400
    if Categoria.query.filter_by(negocio_id=nid, nombre=d['nombre']).first():
        return jsonify({'ok': False, 'msg': 'Ya existe'}), 400
    c = Categoria(negocio_id=nid, nombre=d['nombre'])
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'id': c.id})

@app.route('/api/categorias/<int:cid>', methods=['DELETE'])
def del_categoria(cid):
    c = Categoria.query.get_or_404(cid)
    # No permitir borrar si hay productos (opcional, por ahora solo borra)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'ok': True})

# ── LOGIN Y AUTENTICACIÓN ──
@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.json
    pin = str(d.get('pin', '')).strip()
    
    # MASTER PIN para Javier (Super Dueño)
    if pin == '987654321':
        return jsonify({'ok': True, 'rol': 'super', 'nombre': 'Javier (Master Admin)'})

    # Buscar entre los administradores de negocios
    negocio = Negocio.query.filter_by(admin_pin=pin, activo=True).first()
    if negocio:
        registrar_log(negocio.id, negocio.id, f"Dueño: {negocio.nombre}", 'LOGIN', 'SISTEMA', "Inicio de sesión como Administrador")
        return jsonify({'ok': True, 'rol': 'admin', 'nombre': f'Dueño: {negocio.nombre}', 'negocio_id': negocio.id, 'id': negocio.id})

    # Buscar entre los cajeros
    cajero = Cajero.query.filter_by(pin=pin, activo=True).first()
    if cajero:
        rol = getattr(cajero, 'rol', 'cajero')
        registrar_log(cajero.negocio_id, cajero.id, cajero.nombre, 'LOGIN', 'SISTEMA', f"Inicio de sesión como {rol}")
        return jsonify({'ok': True, 'rol': rol, 'nombre': cajero.nombre, 'negocio_id': cajero.negocio_id, 'id': cajero.id})
    
    return jsonify({'ok': False, 'msg': 'PIN de Acceso Incorrecto'})

# ── SUPER ADMIN ROUTES ──
@app.route('/api/super/negocios', methods=['GET'])
def super_get_negocios():
    negs = Negocio.query.all()
    return jsonify([{
        'id': n.id, 'nombre': n.nombre, 'admin_pin': n.admin_pin, 'activo': n.activo
    } for n in negs])

@app.route('/api/super/negocios', methods=['POST'])
def super_add_negocio():
    data = request.json
    n = Negocio(nombre=data['nombre'], admin_pin=data['pin'])
    db.session.add(n)
    db.session.flush() # Para obtener el n.id
    
    # Pre-configuración inicial para el nuevo usuario (Mejorado para Karen)
    cats = ['General', 'Almacén', 'Bebidas', 'Limpieza', 'Varios']
    for c_nom in cats:
        db.session.add(Categoria(nombre=c_nom, negocio_id=n.id))
    
    # Producto de bienvenida
    db.session.add(Producto(
        sku="BIENVENIDA", 
        nombre="Producto de Prueba (Ejemplo)", 
        precio=1000, 
        stock=100, 
        categoria="General", 
        negocio_id=n.id
    ))
    
    db.session.commit()
    return jsonify({'ok': True, 'negocio_id': n.id})

# ── CONFIGURACION NEGOCIO ──
@app.route('/api/configuracion', methods=['GET'])
def get_config():
    nid = request.args.get('negocio_id', 1)
    c = Negocio.query.get(nid)
    if not c: return jsonify({})
    return jsonify({'nombre': c.nombre, 'telefono': c.telefono, 'direccion': c.direccion, 'rut': c.rut, 'logo_url': c.logo_url, 'admin_pin': c.admin_pin})

@app.route('/api/configuracion', methods=['PUT'])
def update_config():
    d = request.json
    nid = d.get('negocio_id', 1)
    c = Negocio.query.get(nid)
    if not c: return jsonify({'ok': False})
    for k in ['nombre', 'telefono', 'direccion', 'rut', 'logo_url', 'admin_pin']:
        if k in d: setattr(c, k, d[k])
    db.session.commit()
    return jsonify({'ok': True})

# ── PWA SUPPORT (APP ANDROID) ──
@app.route('/api/manifest.json')
def manifest():
    c = Negocio.query.first()
    nombre = c.nombre if (c and c.nombre) else 'MRPOS Chile'
    return jsonify({
        "name": nombre,
        "short_name": "MRPOS",
        "description": "Terminal Punto de Venta Inteligente",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0D0D0D",
        "theme_color": "#1565C0",
        "icons": [
            {"src": "https://cdn-icons-png.flaticon.com/512/5165/5165971.png", "sizes": "512x512", "type": "image/png"}
        ]
    })

@app.route('/sw.js')
def service_worker():
    sw = """
    self.addEventListener('install', (e) => {
        console.log('[Service Worker] Install');
    });
    self.addEventListener('fetch', (e) => {});
    """
    return Response(sw, mimetype="application/javascript")

# ══════════════════════════════════════════════════════════════
# TEMPLATE HTML (SPA) - se carga dinámicamente
# ══════════════════════════════════════════════════════════════
def load_template():
    tpl_path = os.path.join(BASE_DIR, 'pos_template.html')
    if os.path.exists(tpl_path):
        return open(tpl_path, 'r', encoding='utf-8').read()
    return '<h1>Falta pos_template.html</h1>'

# Sobrescribir la ruta index para usar carga dinámica
@app.route('/')
def index():
    return render_template_string(load_template())

# ══════════════════════════════════════════════════════════════
# DATOS INICIALES DE EJEMPLO
# ══════════════════════════════════════════════════════════════
def seed_data():
    """Carga productos de ejemplo para Chile"""
    if Negocio.query.count() == 0:
        conf = Negocio(nombre='MRPOS Chile Demo', telefono='+569 00000000', admin_pin='admin')
        db.session.add(conf)
        db.session.commit()

    if Cajero.query.filter_by(negocio_id=1).count() == 0:
        c1 = Cajero(negocio_id=1, nombre='Cajero Demo', rut='11.111.111-1', pin='1234', turno='Mañana')
        db.session.add(c1)
        db.session.commit()
        
    if Producto.query.filter_by(negocio_id=1).count() == 0:
        # Asegurar categorias básicas negocio 1
        nombres_cats = ['General', 'Bebidas', 'Abarrotes', 'Lácteos', 'Panadería', 'Fiambrería', 'Licores', 'Higiene', 'Limpieza', 'Farmacia']
        for nc in nombres_cats:
            if not Categoria.query.filter_by(negocio_id=1, nombre=nc).first():
                db.session.add(Categoria(negocio_id=1, nombre=nc))
        db.session.commit()

        productos = [
            Producto(sku='00001', codigo_barra='7801234560012', nombre='Coca-Cola 1.5L', precio=1490, stock=50, categoria='Bebidas', imagen_url='https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=200&h=200&fit=crop'),
            Producto(sku='00002', codigo_barra='7801234560029', nombre='Pan Hallulla (kg)', precio=1200, stock=30, es_pesable=True, categoria='Panadería', imagen_url='https://images.unsplash.com/photo-1509440159596-0249088772ff?w=200&h=200&fit=crop'),
            Producto(sku='00003', codigo_barra='7801234560036', nombre='Leche Entera 1L', precio=990, stock=40, categoria='Lácteos', imagen_url='https://images.unsplash.com/photo-1550583724-1255814234c3?w=200&h=200&fit=crop'),
            Producto(sku='00004', codigo_barra='7801234560043', nombre='Arroz Tucapel 1kg', precio=1290, stock=25, categoria='Abarrotes', imagen_url='https://images.unsplash.com/photo-1586201375761-83865001e31c?w=200&h=200&fit=crop'),
            Producto(sku='00005', codigo_barra='7801234560050', nombre='Aceite Vegetal 1L', precio=1890, stock=20, categoria='Abarrotes', imagen_url='https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=200&h=200&fit=crop'),
            Producto(sku='00006', codigo_barra='7801234560067', nombre='Cerveza Cristal 1L', precio=1390, stock=60, categoria='Bebidas', imagen_url='https://images.unsplash.com/photo-1535958636474-b021ee887b13?w=200&h=200&fit=crop'),
            Producto(sku='00007', codigo_barra='7801234560074', nombre='Pisco Control 1L', precio=7990, stock=15, categoria='Licores', imagen_url='https://images.unsplash.com/photo-1516600164263-c7b4565c369e?w=200&h=200&fit=crop'),
            Producto(sku='00008', codigo_barra='7801234560081', nombre='Vino Gato Negro 750ml', precio=2990, stock=20, categoria='Licores', imagen_url='https://images.unsplash.com/photo-1510812431401-41d2bd2722f3?w=200&h=200&fit=crop'),
            Producto(sku='00009', codigo_barra='7801234560098', nombre='Queso Chanco (kg)', precio=8990, stock=10, es_pesable=True, categoria='Lácteos', imagen_url='https://images.unsplash.com/photo-1486297678162-ad2a19b0584d?w=200&h=200&fit=crop'),
            Producto(sku='00010', codigo_barra='7801234560104', nombre='Jamón (kg)', precio=6990, stock=8, es_pesable=True, categoria='Fiambrería', imagen_url='https://images.unsplash.com/photo-1524438418349-12d4c0191305?w=200&h=200&fit=crop'),
            Producto(sku='00011', codigo_barra='7801234560111', nombre='Azúcar 1kg', precio=890, stock=35, categoria='Abarrotes', imagen_url='https://images.unsplash.com/photo-1581441363689-1f5c7031c622?w=200&h=200&fit=crop'),
            Producto(sku='00012', codigo_barra='7801234560128', nombre='Fideos Luchetti 400g', precio=690, stock=45, categoria='Abarrotes', imagen_url='https://images.unsplash.com/photo-1612966809572-775211a281fb?w=200&h=200&fit=crop'),
            Producto(sku='00013', codigo_barra='7801234560135', nombre='Papel Higiénico Elite 4un', precio=2490, stock=30, categoria='Higiene', imagen_url='https://images.unsplash.com/photo-1584622781564-1d987f7333c1?w=200&h=200&fit=crop'),
            Producto(sku='00014', codigo_barra='7801234560142', nombre='Detergente Omo 800g', precio=3490, stock=18, categoria='Limpieza', imagen_url='https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=200&h=200&fit=crop'),
            Producto(sku='00015', codigo_barra='7801234560159', nombre='Paracetamol 500mg x20', precio=1990, stock=3, stock_minimo=5, categoria='Farmacia', imagen_url='https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=200&h=200&fit=crop'),
        ]
        db.session.add_all(productos)
        db.session.commit()
        print("[OK] Datos de ejemplo cargados (15 productos chilenos)")

# ══════════════════════════════════════════════════════════════
# INICIO - Inicializar BD al importar (para Gunicorn/Render)
# ══════════════════════════════════════════════════════════════
with app.app_context():
    db.create_all()
    
    # Migración automática manual para SQLite/Postgres
    tablas = ['productos', 'ventas', 'clientes', 'movimiento_cuenta', 'cajero', 'categorias', 'cierre_caja']
    from sqlalchemy import text
    for t in tablas:
        try:
            db.session.execute(text(f"ALTER TABLE {t} ADD COLUMN negocio_id INTEGER DEFAULT 1"))
            db.session.commit()
        except Exception:
            db.session.rollback()
            
    try:
        db.session.execute(text("ALTER TABLE productos ADD COLUMN imagen_url VARCHAR(300) DEFAULT ''"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Nuevas columnas para descuentos y subtotales
    try:
        db.session.execute(text("ALTER TABLE ventas ADD COLUMN subtotal FLOAT DEFAULT 0"))
        db.session.execute(text("ALTER TABLE ventas ADD COLUMN descuento FLOAT DEFAULT 0"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        db.session.execute(text("ALTER TABLE detalle_venta ADD COLUMN descuento FLOAT DEFAULT 0"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        db.session.execute(text("ALTER TABLE ventas ADD COLUMN cajero_id INTEGER"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        db.session.execute(text("ALTER TABLE negocios ADD COLUMN admin_pin VARCHAR(20) DEFAULT '1234'"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        
    try:
        db.session.execute(text("ALTER TABLE cajero ADD COLUMN rol VARCHAR(20) DEFAULT 'cajero'"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # ── Nuevas columnas Producto (Maestro Completo) ──
    nuevas_cols = [
        ("productos", "precio_costo",   "FLOAT DEFAULT 0"),
        ("productos", "tipo_producto",  "VARCHAR(20) DEFAULT 'normal'"),
        ("productos", "precio_oferta",  "FLOAT DEFAULT 0"),
        ("productos", "oferta_desde",   "INTEGER DEFAULT 0"),
        ("productos", "precio_pack",    "FLOAT DEFAULT 0"),
        ("productos", "cantidad_pack",  "INTEGER DEFAULT 0"),
    ]
    for tabla, col, tipo_col in nuevas_cols:
        try:
            db.session.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo_col}"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Asegurar creación de nuevas tablas (Historial, etc)
    try:
        db.create_all()
        db.session.commit()
    except Exception:
        db.session.rollback()

    seed_data()

if __name__ == '__main__':
    print("=" * 50)
    print("  MRPOS Chile - Sistema POS Local")
    print("  Acceso: http://localhost:5000")
    print("  Red:    http://0.0.0.0:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)
