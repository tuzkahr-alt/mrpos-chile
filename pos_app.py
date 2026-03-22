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
class Producto(db.Model):
    __tablename__ = 'productos'
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(20), unique=True, nullable=False)
    codigo_barra = db.Column(db.String(20), default='')
    nombre = db.Column(db.String(100), nullable=False)
    precio = db.Column(db.Float, nullable=False, default=0)
    stock = db.Column(db.Float, nullable=False, default=0)
    es_pesable = db.Column(db.Boolean, default=False)
    categoria = db.Column(db.String(50), default='General')
    stock_minimo = db.Column(db.Float, default=5)
    activo = db.Column(db.Boolean, default=True)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

class Venta(db.Model):
    __tablename__ = 'ventas'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    total = db.Column(db.Float, nullable=False)
    metodo_pago = db.Column(db.String(20), default='Efectivo')  # Efectivo, Debito, Credito, Fiado
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    monto_pagado = db.Column(db.Float, default=0)
    vuelto = db.Column(db.Float, default=0)
    detalles = db.relationship('DetalleVenta', backref='venta', lazy=True)
    cliente = db.relationship('Cliente', backref='ventas')

class DetalleVenta(db.Model):
    __tablename__ = 'detalle_venta'
    id = db.Column(db.Integer, primary_key=True)
    venta_id = db.Column(db.Integer, db.ForeignKey('ventas.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    cantidad = db.Column(db.Float, nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    producto = db.relationship('Producto')

class CierreCaja(db.Model):
    __tablename__ = 'cierre_caja'
    id = db.Column(db.Integer, primary_key=True)
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
    nombre = db.Column(db.String(100), nullable=False)
    rut = db.Column(db.String(15), default='')
    telefono = db.Column(db.String(20), default='')
    email = db.Column(db.String(100), default='')
    direccion = db.Column(db.String(200), default='')
    saldo_pendiente = db.Column(db.Float, default=0)  # Deuda acumulada
    activo = db.Column(db.Boolean, default=True)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

class MovimientoCuenta(db.Model):
    __tablename__ = 'movimiento_cuenta'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    tipo = db.Column(db.String(10))  # 'cargo' o 'abono'
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(200), default='')
    venta_id = db.Column(db.Integer, db.ForeignKey('ventas.id'), nullable=True)
    cliente = db.relationship('Cliente', backref='movimientos')

class Cajero(db.Model):
    __tablename__ = 'cajeros'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    rut = db.Column(db.String(15), default='')
    pin = db.Column(db.String(10), default='1234')
    turno = db.Column(db.String(50), default='Mañana')
    activo = db.Column(db.Boolean, default=True)

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
    productos = Producto.query.filter_by(activo=True).all()
    return jsonify([{
        'id': p.id, 'sku': p.sku, 'codigo_barra': p.codigo_barra,
        'nombre': p.nombre, 'precio': p.precio, 'stock': p.stock,
        'es_pesable': p.es_pesable, 'categoria': p.categoria,
        'stock_minimo': p.stock_minimo
    } for p in productos])

@app.route('/api/productos', methods=['POST'])
def crear_producto():
    d = request.json
    p = Producto(sku=d['sku'], nombre=d['nombre'], precio=float(d['precio']),
                 stock=float(d.get('stock', 0)), es_pesable=d.get('es_pesable', False),
                 codigo_barra=d.get('codigo_barra', ''), categoria=d.get('categoria', 'General'),
                 stock_minimo=float(d.get('stock_minimo', 5)))
    db.session.add(p)
    db.session.commit()
    return jsonify({'ok': True, 'id': p.id})

@app.route('/api/productos/<int:pid>', methods=['PUT'])
def editar_producto(pid):
    p = Producto.query.get_or_404(pid)
    d = request.json
    for k in ['nombre', 'precio', 'stock', 'es_pesable', 'codigo_barra', 'categoria', 'stock_minimo', 'sku']:
        if k in d:
            setattr(p, k, float(d[k]) if k in ['precio','stock','stock_minimo'] else d[k])
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/productos/<int:pid>', methods=['DELETE'])
def eliminar_producto(pid):
    p = Producto.query.get_or_404(pid)
    p.activo = False
    db.session.commit()
    return jsonify({'ok': True})

# ── BUSCAR POR CÓDIGO (Barras / Balanza) ──
@app.route('/api/buscar_codigo', methods=['POST'])
def buscar_codigo():
    codigo = request.json.get('codigo', '').strip()
    # Verificar si es código de balanza Digi SM-100
    info_balanza = procesar_codigo_balanza(codigo)
    if info_balanza['es_balanza']:
        prod = Producto.query.filter_by(sku=info_balanza['sku'], activo=True).first()
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
        (Producto.codigo_barra == codigo) | (Producto.sku == codigo),
        Producto.activo == True
    ).first()
    if prod:
        return jsonify({
            'encontrado': True, 'es_balanza': False,
            'producto': {'id': prod.id, 'sku': prod.sku, 'nombre': prod.nombre,
                         'precio': prod.precio, 'stock': prod.stock, 'es_pesable': prod.es_pesable}
        })
    return jsonify({'encontrado': False, 'es_balanza': False})

# ── VENTAS ──
@app.route('/api/ventas', methods=['POST'])
def crear_venta():
    d = request.json
    items = d.get('items', [])
    metodo = d.get('metodo_pago', 'Efectivo')
    cliente_id = d.get('cliente_id', None)
    monto_pagado = float(d.get('monto_pagado', 0))
    total = 0
    venta = Venta(total=0, metodo_pago=metodo, cliente_id=cliente_id,
                  monto_pagado=monto_pagado)
    db.session.add(venta)
    db.session.flush()
    detalles_resp = []
    for item in items:
        prod = Producto.query.get(item['producto_id'])
        if not prod:
            continue
        cant = float(item['cantidad'])
        precio_u = float(item.get('precio_unitario', prod.precio))
        sub = round(cant * precio_u, 0)
        det = DetalleVenta(venta_id=venta.id, producto_id=prod.id,
                           cantidad=cant, precio_unitario=precio_u, subtotal=sub)
        db.session.add(det)
        prod.stock = max(0, prod.stock - cant)
        total += sub
        detalles_resp.append({'nombre': prod.nombre, 'cantidad': cant,
                              'precio_unitario': precio_u, 'subtotal': sub})
    venta.total = total
    vuelto = max(0, monto_pagado - total) if metodo == 'Efectivo' else 0
    venta.vuelto = vuelto
    # Si es Fiado, registrar en cuenta del cliente
    if metodo == 'Fiado' and cliente_id:
        cli = Cliente.query.get(cliente_id)
        if cli:
            cli.saldo_pendiente += total
            mov = MovimientoCuenta(cliente_id=cli.id, tipo='cargo', monto=total,
                                   descripcion=f'Venta #{venta.id}', venta_id=venta.id)
            db.session.add(mov)
    db.session.commit()
    return jsonify({'ok': True, 'venta_id': venta.id, 'total': total,
                    'vuelto': vuelto, 'metodo_pago': metodo,
                    'monto_pagado': monto_pagado, 'detalles': detalles_resp})

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
    ventas = Venta.query.filter(db.func.date(Venta.fecha) == hoy).all()
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
    ventas = Venta.query.filter(db.func.date(Venta.fecha) == hoy).all()
    t_ef = sum(v.total for v in ventas if v.metodo_pago == 'Efectivo')
    t_db = sum(v.total for v in ventas if v.metodo_pago == 'Debito')
    t_cr = sum(v.total for v in ventas if v.metodo_pago == 'Credito')
    t_fi = sum(v.total for v in ventas if v.metodo_pago == 'Fiado')
    cierre = CierreCaja(total_efectivo=t_ef, total_debito=t_db, total_credito=t_cr,
                        total_fiado=t_fi, total_general=t_ef+t_db+t_cr+t_fi, num_ventas=len(ventas))
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
    ventas_hoy_q = Venta.query.filter(db.func.date(Venta.fecha) == hoy).all()
    total_hoy = sum(v.total for v in ventas_hoy_q)
    bajo_stock = Producto.query.filter(Producto.stock <= Producto.stock_minimo, Producto.activo == True).all()
    total_productos = Producto.query.filter_by(activo=True).count()
    return jsonify({
        'ventas_hoy': len(ventas_hoy_q), 'total_hoy': total_hoy,
        'total_productos': total_productos,
        'bajo_stock': [{'id': p.id, 'nombre': p.nombre, 'stock': p.stock, 'stock_minimo': p.stock_minimo} for p in bajo_stock],
        'ultimas_ventas': [{'id': v.id, 'total': v.total, 'metodo_pago': v.metodo_pago,
                            'hora': v.fecha.strftime('%H:%M')} for v in ventas_hoy_q[-10:]]
    })

# ── PRODUCTOS BAJO STOCK ──
@app.route('/api/alertas', methods=['GET'])
def alertas():
    bajo = Producto.query.filter(Producto.stock <= Producto.stock_minimo, Producto.activo == True).all()
    return jsonify([{'id': p.id, 'nombre': p.nombre, 'stock': p.stock, 'stock_minimo': p.stock_minimo} for p in bajo])

# ── CLIENTES ──
@app.route('/api/clientes', methods=['GET'])
def get_clientes():
    clientes = Cliente.query.filter_by(activo=True).all()
    return jsonify([{'id': c.id, 'nombre': c.nombre, 'rut': c.rut,
                     'telefono': c.telefono, 'email': c.email,
                     'direccion': c.direccion, 'saldo_pendiente': c.saldo_pendiente
    } for c in clientes])

@app.route('/api/clientes', methods=['POST'])
def crear_cliente():
    d = request.json
    c = Cliente(nombre=d['nombre'], rut=d.get('rut',''), telefono=d.get('telefono',''),
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
    mov = MovimientoCuenta(cliente_id=cid, tipo='abono', monto=monto,
                           descripcion=d.get('descripcion', 'Abono de cliente'))
    db.session.add(mov)
    c.saldo_pendiente = max(0, c.saldo_pendiente - monto)
    db.session.commit()
    return jsonify({'ok': True, 'saldo_pendiente': c.saldo_pendiente})

# ── INFORMES ──
@app.route('/api/informes/stock_categoria', methods=['GET'])
def informe_stock_categoria():
    productos = Producto.query.filter_by(activo=True).all()
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
    ventas_hoy = Venta.query.filter(db.func.date(Venta.fecha) == hoy).all()
    todas = Venta.query.all()
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
        productos = Producto.query.filter_by(activo=True).all()
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

# ── CAJEROS ──
@app.route('/api/cajeros', methods=['GET'])
def get_cajeros():
    cajeros = Cajero.query.filter_by(activo=True).all()
    return jsonify([{'id': c.id, 'nombre': c.nombre, 'rut': c.rut, 'pin': c.pin, 'turno': c.turno} for c in cajeros])

@app.route('/api/cajeros', methods=['POST'])
def crear_cajero():
    d = request.json
    c = Cajero(nombre=d['nombre'], rut=d.get('rut',''), pin=d.get('pin','1234'), turno=d.get('turno','Mañana'))
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'id': c.id})

@app.route('/api/cajeros/<int:cid>', methods=['DELETE'])
def eliminar_cajero(cid):
    c = Cajero.query.get_or_404(cid)
    c.activo = False
    db.session.commit()
    return jsonify({'ok': True})

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
    if Cajero.query.count() == 0:
        c1 = Cajero(nombre='Cajero Principal', rut='11.111.111-1', pin='1234', turno='Mañana')
        db.session.add(c1)
        db.session.commit()
        
    if Producto.query.count() == 0:
        productos = [
            Producto(sku='00001', codigo_barra='7801234560012', nombre='Coca-Cola 1.5L', precio=1490, stock=50, categoria='Bebidas'),
            Producto(sku='00002', codigo_barra='7801234560029', nombre='Pan Hallulla (kg)', precio=1200, stock=30, es_pesable=True, categoria='Panadería'),
            Producto(sku='00003', codigo_barra='7801234560036', nombre='Leche Entera 1L', precio=990, stock=40, categoria='Lácteos'),
            Producto(sku='00004', codigo_barra='7801234560043', nombre='Arroz Tucapel 1kg', precio=1290, stock=25, categoria='Abarrotes'),
            Producto(sku='00005', codigo_barra='7801234560050', nombre='Aceite Vegetal 1L', precio=1890, stock=20, categoria='Abarrotes'),
            Producto(sku='00006', codigo_barra='7801234560067', nombre='Cerveza Cristal 1L', precio=1390, stock=60, categoria='Bebidas'),
            Producto(sku='00007', codigo_barra='7801234560074', nombre='Pisco Control 1L', precio=7990, stock=15, categoria='Licores'),
            Producto(sku='00008', codigo_barra='7801234560081', nombre='Vino Gato Negro 750ml', precio=2990, stock=20, categoria='Licores'),
            Producto(sku='00009', codigo_barra='7801234560098', nombre='Queso Chanco (kg)', precio=8990, stock=10, es_pesable=True, categoria='Lácteos'),
            Producto(sku='00010', codigo_barra='7801234560104', nombre='Jamón (kg)', precio=6990, stock=8, es_pesable=True, categoria='Fiambrería'),
            Producto(sku='00011', codigo_barra='7801234560111', nombre='Azúcar 1kg', precio=890, stock=35, categoria='Abarrotes'),
            Producto(sku='00012', codigo_barra='7801234560128', nombre='Fideos Luchetti 400g', precio=690, stock=45, categoria='Abarrotes'),
            Producto(sku='00013', codigo_barra='7801234560135', nombre='Papel Higiénico Elite 4un', precio=2490, stock=30, categoria='Higiene'),
            Producto(sku='00014', codigo_barra='7801234560142', nombre='Detergente Omo 800g', precio=3490, stock=18, categoria='Limpieza'),
            Producto(sku='00015', codigo_barra='7801234560159', nombre='Paracetamol 500mg x20', precio=1990, stock=3, stock_minimo=5, categoria='Farmacia'),
        ]
        db.session.add_all(productos)
        db.session.commit()
        print("[OK] Datos de ejemplo cargados (15 productos chilenos)")

# ══════════════════════════════════════════════════════════════
# INICIO - Inicializar BD al importar (para Gunicorn/Render)
# ══════════════════════════════════════════════════════════════
with app.app_context():
    db.create_all()
    seed_data()

if __name__ == '__main__':
    print("=" * 50)
    print("  MRPOS Chile - Sistema POS Local")
    print("  Acceso: http://localhost:5000")
    print("  Red:    http://0.0.0.0:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)
