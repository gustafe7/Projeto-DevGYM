from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime
import re
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'
database_url = os.environ.get('DATABASE_URL', 'sqlite:///database.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
db = SQLAlchemy(app)
serializer = URLSafeTimedSerializer(app.secret_key)

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587   
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
mail = Mail(app)

def email_valido(email):
    padrao = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(padrao, email)

def senha_forte(senha):
    if len(senha) < 8:
        return False
    if not any(c.isupper() for c in senha):
        return False
    if not any(c.isdigit() for c in senha):
        return False
    return True

def gerar_token(usuario_email):
    return serializer.dumps(usuario_email, salt='recuperar-senha')

def calcular_streak(usuario_id):
    from datetime import date, timedelta
    sessoes = SessaoTreino.query.filter_by(usuario_id=usuario_id).order_by(SessaoTreino.data.desc()).all()
    datas = list(set(s.data for s in sessoes))
    datas.sort(reverse=True)

    if not datas:
        return 0

    hoje = date.today()

    if datas[0] == hoje:
        inicio = hoje
    else:
        inicio = hoje - timedelta(days=1)
    streak = 0

    for i, data in enumerate(datas):
        esperado = hoje - timedelta(days=i)
        if data == esperado:
            streak += 1
        else:
            break

    return streak

def calcular_streak_max(usuario_id):
    from datetime import timedelta

    sessoes = SessaoTreino.query.filter_by(usuario_id=usuario_id)\
        .order_by(SessaoTreino.data.asc()).all()

    datas = list(set(s.data for s in sessoes))
    datas.sort()

    if not datas:
        return 0

    max_streak = 1
    streak_atual = 1

    for i in range(1, len(datas)):
        if datas[i] == datas[i-1] + timedelta(days=1):
            streak_atual += 1
            if streak_atual > max_streak:
                max_streak = streak_atual
        else:
            streak_atual = 1

    return max_streak

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    senha = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    confirmado = db.Column(db.Boolean, default=False)

class Treino(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dia_semana = db.Column(db.String(20), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    ativo = db.Column(db.Boolean, default=True)
    notas = db.Column(db.Text, default="")

    # Relacionamento com cascade para deletar exercícios quando um treino for deletado
    exercicios = db.relationship('Exercicio', backref='treino', cascade="all, delete-orphan")

class Exercicio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    treino_id = db.Column(db.Integer, db.ForeignKey('treino.id'), nullable=False)
    concluido = db.Column(db.Boolean, default=False)
    series = db.Column(db.Integer, default=3)
    repeticoes = db.Column(db.Integer, default=10)
    carga = db.Column(db.Float, default=0.0)
    ordem = db.Column(db.Integer, default=0)

class SessaoTreino(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    treino_id = db.Column(db.Integer, db.ForeignKey('treino.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    data = db.Column(db.Date, nullable=False)
    total_exercicios = db.Column(db.Integer, nullable=False)
    exercicios_concluidos = db.Column(db.Integer, nullable=False)    

class HistoricoCarga(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    exercicio_nome = db.Column(db.String(100), nullable=False)
    carga = db.Column(db.Float, nullable=False)
    data = db.Column(db.Date, nullable=False)

with app.app_context():
    db.create_all()

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')

@app.route('/')
def index():
    if 'usuario_id' not in session:
        return redirect('/login')
    treinos = Treino.query.filter_by(usuario_id=session['usuario_id'], ativo=True).all()
    return render_template('index.html', treinos=treinos)

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    erro = None
    sucesso = False

    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']
        senha_confirm = request.form['senha_confirm']
        
        if not email_valido(email):
            erro = "E-mail inválido!"
        elif Usuario.query.filter_by(email=email).first():
            erro = "E-mail já cadastrado!"
        elif senha != senha_confirm:
            erro = "As senhas não coincidem!"
        elif not senha_forte(senha):
            erro = "A senha deve ter pelo menos 8 caracteres, incluir uma letra maiúscula e um número!"
        else:
            senha_hash = generate_password_hash(senha)
            novo_usuario = Usuario(nome=nome, senha=senha_hash, email=email, confirmado=False) 
            db.session.add(novo_usuario)
            db.session.commit()
            token = serializer.dumps(email, salt='confirmar-email')
            link = url_for('confirmar_email', token=token, _external=True)
            msg = Message(subject="🏋️ Bem-vindo ao DevGym!",
              sender=app.config['MAIL_USERNAME'],
              recipients=[email],
              body=f"""Fala, {nome}! 

Que bom ter você por aqui!

Só falta um passo para começar a montar sua rotina de treinos no DevGym. Confirme seu e-mail clicando no link abaixo:

👉 {link}

O link é válido por 1 hora.

⚠️ Este é um e-mail automático, por favor não responda.

Bora treinar! 💪
— Equipe DevGym""")
            mail.send(msg)
            sucesso = True
    return render_template('login.html', erro=erro, sucesso=sucesso)

@app.route('/confirmar/<token>')
def confirmar_email(token):
    try:
        email = serializer.loads(token, salt='confirmar-email', max_age=3600)  # 1 hora de validade
    except:
        return "Link inválido ou expirado!"

    usuario = Usuario.query.filter_by(email=email).first()
    if usuario:
        usuario.confirmado = True
        db.session.commit()
        return render_template('email_confirmado.html')
    return "Usuário não encontrado."

@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario:
            if not usuario.confirmado:
                erro = "Por favor, confirme seu e-mail antes de fazer login."
            elif check_password_hash(usuario.senha, senha):
                session['usuario_id'] = usuario.id
                return redirect('/')
            else:
                erro = "E-mail ou senha incorretos!"
        else:
            erro = "E-mail ou senha incorretos!"  
    return render_template('login.html', erro=erro)

@app.route('/perfil')
def perfil():
    if 'usuario_id' not in session:
        return redirect('/login')
    
    usuario = Usuario.query.get_or_404(session['usuario_id'])

    # Apenas histórico (treinos inativos)
    treinos_inativos = Treino.query.filter_by(
        usuario_id=usuario.id,
        ativo=False
    ).order_by(Treino.data_criacao.desc()).all()

    streak = calcular_streak(usuario.id)
    streak_max = calcular_streak_max(usuario.id)
    return render_template('perfil.html',usuario=usuario,treinos_inativos=treinos_inativos, streak=streak, streak_max=streak_max)

@app.route('/desempenho')
def desempenho():
    if 'usuario_id' not in session:
        return redirect('/login')

    usuario_id = session['usuario_id']

    sessoes = SessaoTreino.query.filter_by(usuario_id=usuario_id).order_by(SessaoTreino.data.desc()).all()

    total_sessoes = len(sessoes)
    treinos_completos = sum(1 for s in sessoes if s.exercicios_concluidos == s.total_exercicios)
    treinos_incompletos = total_sessoes - treinos_completos

    total_exercicios_feitos = sum(s.exercicios_concluidos for s in sessoes)
    total_exercicios_possiveis = sum(s.total_exercicios for s in sessoes)

    pct_treinos = int((treinos_completos / total_sessoes) * 100) if total_sessoes > 0 else 0
    pct_exercicios = int((total_exercicios_feitos / total_exercicios_possiveis) * 100) if total_exercicios_possiveis > 0 else 0

    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 10

    from collections import Counter

    meses_nomes = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
                'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

    frequencia_mensal = Counter(s.data.month for s in sessoes)
    labels = meses_nomes
    valores = [frequencia_mensal.get(i + 1, 0) for i in range(12)]

    treinos_inativos = Treino.query.filter_by(usuario_id=usuario_id, ativo=False).order_by(Treino.data_criacao.desc()).paginate(page=pagina, per_page=por_pagina, error_out=False)

    exercicios_nomes = db.session.query(HistoricoCarga.exercicio_nome).filter_by(
        usuario_id=usuario_id
    ).distinct().all()
    exercicios_nomes = [e[0] for e in exercicios_nomes]

    exercicio_selecionado = request.args.get('exercicio', exercicios_nomes[0] if exercicios_nomes else None)

    dados_carga = []
    if exercicio_selecionado:
        dados_carga = HistoricoCarga.query.filter_by(
            usuario_id=usuario_id,
            exercicio_nome=exercicio_selecionado
        ).order_by(HistoricoCarga.data).all()

    labels_carga = [str(d.data) for d in dados_carga]
    valores_carga = [d.carga for d in dados_carga]
    streak = calcular_streak(usuario_id)
    streak_max = calcular_streak_max(usuario_id)

    return render_template('desempenho.html',
        total_sessoes=total_sessoes,
        treinos_completos=treinos_completos,
        treinos_incompletos=treinos_incompletos,
        total_exercicios_feitos=total_exercicios_feitos,
        total_exercicios_possiveis=total_exercicios_possiveis,
        pct_treinos=pct_treinos,
        pct_exercicios=pct_exercicios,
        sessoes=sessoes,
        labels=labels,
        valores=valores,
        treinos_inativos=treinos_inativos,
        exercicios_nomes=exercicios_nomes,
        exercicio_selecionado=exercicio_selecionado,
        labels_carga=labels_carga,
        valores_carga=valores_carga,
        streak=streak,
        streak_max=streak_max,)

@app.route('/perfil/editar-nome', methods=['POST'])
def editar_nome():
    if 'usuario_id' not in session:
        return redirect('/login')

    novo_nome = request.form['nome']

    usuario = Usuario.query.get_or_404(session['usuario_id'])
    usuario.nome = novo_nome

    db.session.commit()

    return redirect('/perfil')

@app.route("/enviar-recuperacao", methods=["POST"])
def enviar_recuperacao():
    email = request.form.get("email")
    usuario = Usuario.query.filter_by(email=email).first()
    
    if usuario:
        token = gerar_token(usuario.email)
        link = url_for('redefinir_senha', token=token, _external=True)
        msg = Message(subject="🔑 Redefinir senha - DevGym",
              sender=app.config['MAIL_USERNAME'],
              recipients=[email],
              body=f"""Fala, {usuario.nome}! 

Recebemos uma solicitação para redefinir a senha da sua conta no DevGym.

Clique no link abaixo para criar uma nova senha:

👉 {link}

O link é válido por 1 hora. Se você não solicitou a redefinição, pode ignorar este e-mail.

⚠️ Este é um e-mail automático, por favor não responda.

— Equipe DevGym""")
        mail.send(msg)

    return "Se o e-mail estiver cadastrado, você receberá instruções para redefinir sua senha."

@app.route('/recuperar-senha')
def recuperar_senha():
    return render_template('recuperar_senha.html')

@app.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    erro = None
    sucesso = False
    email = None
    try:
        email = serializer.loads(token, salt='recuperar-senha', max_age=3600)  # token válido por 1 hora
    except:
        erro = "Link inválido ou expirado!"
        return render_template('redefinir_senha.html', erro=erro, sucesso=sucesso)

    if request.method == 'POST':
        nova_senha = request.form['senha']
        senha_confirm = request.form['senha_confirm']
        
        if not nova_senha or not senha_confirm:
            erro = "Preencha todos os campos!"
        elif nova_senha != senha_confirm:
            erro = "As senhas não coincidem"
        else:
            usuario = Usuario.query.filter_by(email=email).first()
            if usuario:
                usuario.senha = nova_senha
                db.session.commit()
                sucesso = True
            else:
                erro = "Usuário não encontrado!"
    return render_template('redefinir_senha.html', erro=erro, sucesso=sucesso)

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('usuario_id', None)
    return redirect('/login')

@app.route('/submit', methods=['POST'])
def submit():
    nome = request.form['nome']
    senha = request.form['senha']

    novo_usuario = Usuario(nome=nome, senha=senha)
    db.session.add(novo_usuario)
    db.session.commit()
    return redirect('/')

@app.route('/treino', methods=['POST'])
def treino():
    if 'usuario_id' not in session:
        return redirect('/login')
    dia_semana = request.form['dia_semana']
    nome_treino = request.form['nome_treino']
    usuario_id = session['usuario_id']

    novo_treino = Treino(dia_semana=dia_semana, nome=nome_treino, usuario_id=usuario_id)
    db.session.add(novo_treino)
    db.session.commit()
    return redirect('/')

@app.route('/treino/<int:id>/encerrar', methods=['POST'])
def encerrar_treino(id):
    if 'usuario_id' not in session:
        return redirect('/login')

    treino = Treino.query.filter_by(id=id, usuario_id=session['usuario_id']).first_or_404()

    exercicios = Exercicio.query.filter_by(treino_id=id).all()
    total = len(exercicios)
    feitos = sum(1 for e in exercicios if e.concluido)

    
    if total > 0:
        sessao = SessaoTreino(
            treino_id=id,
            usuario_id=session['usuario_id'],
            data=datetime.utcnow().date(),
            total_exercicios=total,
            exercicios_concluidos=feitos
        )
        db.session.add(sessao)

    for e in exercicios:
        if e.carga and e.carga > 0:
            historico = HistoricoCarga(
                usuario_id=session['usuario_id'],
                exercicio_nome=e.nome,
                carga=e.carga,
                data=datetime.utcnow().date()
            )
            db.session.add(historico)

    # Reseta os exercícios
    for e in exercicios:
        e.concluido = False

    db.session.commit()

    return redirect('/')

@app.route('/treino/<int:id>/editar', methods=['GET', 'POST'])
def editar_treino(id):
    if 'usuario_id' not in session:
        return redirect('/login')

    treino = Treino.query.filter_by(id=id, usuario_id=session['usuario_id']).first_or_404()

    if request.method == 'POST':
        treino.nome = request.form['nome']
        treino.dia_semana = request.form['dia_semana']

        db.session.commit()
        return redirect('/')

    return render_template('editar_treino.html', treino=treino)

@app.route('/treino/<int:id>/restaurar', methods=['POST'])
def restaurar_treino(id):
    if 'usuario_id' not in session:
        return '', 401

    treino = Treino.query.filter_by(id=id, usuario_id=session['usuario_id']).first_or_404()
    treino.ativo = True
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return '', 204

    return redirect('/')

@app.route('/treino/<int:treino_id>/notas', methods=['POST'])
def salvar_notas(treino_id):
    if 'usuario_id' not in session:
        return '', 401
    
    treino = Treino.query.filter_by(id=treino_id, usuario_id=session['usuario_id']).first_or_404()
    treino.notas = request.form.get('notas', '')
    db.session.commit()
    flash('Notas salvas com sucesso!')
    return redirect(url_for('treinos_detalhes', treino_id=treino_id))

@app.route('/treino/<int:treino_id>/exercicio', methods=['GET', 'POST'])
def exercicio(treino_id):
    if 'usuario_id' not in session:
        return redirect('/login')

    treino = Treino.query.filter_by(id=treino_id, usuario_id=session['usuario_id']).first_or_404()

    if request.method == 'POST':
        nome_exercicio = request.form['nome_exercicio']
        novo_exercicio = Exercicio(nome=nome_exercicio, treino_id=treino_id)
        db.session.add(novo_exercicio)
        db.session.commit()
        return redirect(f'/treino/{treino_id}')
    return render_template('exercicio.html', treino=treino)

@app.route('/exercicio/<int:id>/editar', methods=['POST'])
def editar_exercicio(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    
    exercicio = Exercicio.query.get_or_404(id)
    exercicio.nome = request.form.get('nome', exercicio.nome)
    exercicio.series = int(request.form.get('series', exercicio.series))
    exercicio.repeticoes = int(request.form.get('repeticoes', exercicio.repeticoes))
    exercicio.carga = float(request.form.get('carga', exercicio.carga))
    
    db.session.commit()
    return redirect(f'/treino/{exercicio.treino_id}')

@app.route('/treino/<int:treino_id>/reordenar', methods=['POST'])
def reordenar_exercicios(treino_id):
    if 'usuario_id' not in session:
        return '', 401
    
    dados = request.get_json()
    for item in dados:
        exercicio = Exercicio.query.get(item['id'])
        if exercicio:
            exercicio.ordem = item['ordem']
    
    db.session.commit()
    return '', 204

@app.route('/treino/<int:treino_id>', methods=['GET', 'POST'])
def treinos_detalhes(treino_id):
    if 'usuario_id' not in session:
        return redirect('/login')
    
    treino = Treino.query.filter_by(id=treino_id,usuario_id=session['usuario_id']).first_or_404()
    
    if request.method == 'POST':
        nome_exercicio = request.form['nome_exercicio']
        novo_exercicio = Exercicio(
        nome=nome_exercicio,
        treino_id=treino_id,
        series=int(request.form.get('series', 3)),
        repeticoes=int(request.form.get('repeticoes', 10)),
        carga=float(request.form.get('carga', 0.0))
        )
        db.session.add(novo_exercicio)
        db.session.commit()
        return redirect(url_for('treinos_detalhes', treino_id=treino_id))

    exercicios = Exercicio.query.filter_by(treino_id=treino_id).order_by(Exercicio.ordem).all()

    
    total = len(exercicios)
    feitos = sum(1 for e in exercicios if e.concluido)
    progresso = int((feitos / total) * 100) if total > 0 else 0
    
    return render_template('treino_detalhes.html', treino=treino, exercicios=exercicios, progresso=progresso)

@app.route('/exercicio/<int:id>/concluir', methods=['POST'])
def concluir_exercicio(id):
    if 'usuario_id' not in session:
        return '', 401
    exercicio = Exercicio.query.get_or_404(id)
    treino = Treino.query.filter_by(id=exercicio.treino_id, usuario_id=session['usuario_id']).first_or_404()
    exercicio.concluido = not exercicio.concluido
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        exercicios = Exercicio.query.filter_by(treino_id=exercicio.treino_id).all()
        total = len(exercicios)
        feitos = sum(1 for e in exercicios if e.concluido)
        progresso = int((feitos / total) * 100) if total > 0 else 0
        return {'concluido': exercicio.concluido, 'progresso': progresso}

    return redirect(f'/treino/{exercicio.treino_id}')

@app.route('/exercicio/<int:id>/delete', methods=['POST'])
def deletar_exercicio(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    
    exercicio = Exercicio.query.get_or_404(id)
    treino_id = exercicio.treino_id

    db.session.delete(exercicio)
    db.session.commit()
    
    return redirect(f'/treino/{treino_id}')

@app.route('/treino/<int:id>/delete', methods=['POST'])
def deletar_treino(id):
    if 'usuario_id' not in session:
        return redirect('/login')

    treino = Treino.query.filter_by(id=id, usuario_id=session['usuario_id']).first_or_404()

    treino.ativo = False  
    db.session.commit()

    return redirect('/')

@app.route('/treino/<int:id>/delete-permanente', methods=['POST'])
def deletar_treino_permanente(id):
    if 'usuario_id' not in session:
        return redirect('/login')

    treino = Treino.query.filter_by(id=id, usuario_id=session['usuario_id']).first_or_404()

    db.session.delete(treino)  
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return '', 204

    return redirect('/')

@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    usuario = Usuario.query.get_or_404(id)
    db.session.delete(usuario)
    db.session.commit()
    return redirect('/')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False)
