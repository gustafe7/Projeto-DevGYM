from flask import Flask, render_template, request, redirect, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime
import re
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
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

def gerar_token(usuario_email):
    return serializer.dumps(usuario_email, salt='recuperar-senha')

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    confirmado = db.Column(db.Boolean, default=False)

class Treino(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dia_semana = db.Column(db.String(20), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    ativo = db.Column(db.Boolean, default=True)

    # Relacionamento com cascade para deletar exercícios quando um treino for deletado
    exercicios = db.relationship('Exercicio', backref='treino', cascade="all, delete-orphan")

class Exercicio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    treino_id = db.Column(db.Integer, db.ForeignKey('treino.id'), nullable=False)
    concluido = db.Column(db.Boolean, default=False)
    
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
        else:
            novo_usuario = Usuario(nome=nome, senha=senha, email=email, confirmado=False) 
            db.session.add(novo_usuario)
            db.session.commit()
            token = serializer.dumps(email, salt='confirmar-email')
            link = url_for('confirmar_email', token=token, _external=True)
            msg = Message(subject="Confirme seu cadastro", 
                          sender=app.config['MAIL_USERNAME'], 
                          recipients=[email],
                          body=f"Olá {nome},\n\nPor favor, clique no link abaixo para confirmar seu cadastro: {link}")
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
        return "E-mail confirmado! Agora você pode fazer login."
    return "Usuário não encontrado."

@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None
    if request.method == 'POST':
        nome = request.form['nome']
        senha = request.form['senha']
        usuario = Usuario.query.filter_by(nome=nome, senha=senha).first()
        if usuario:
            if not usuario.confirmado:
                erro = "Por favor, confirme seu e-mail antes de fazer login."
            else:
                session['usuario_id'] = usuario.id
                return redirect('/')
        else:
            erro = "Login ou senha incorretos!"  
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

    # Filtros
    nome_filtro = request.args.get('nome', '').strip()
    mes_filtro = request.args.get('mes')

    if nome_filtro:
        treinos_inativos = [t for t in treinos_inativos if nome_filtro.lower() in t.nome.lower()]
    if mes_filtro:
        treinos_inativos = [t for t in treinos_inativos if t.data_criacao.month == int(mes_filtro)]

    return render_template('perfil.html',usuario=usuario,treinos_inativos=treinos_inativos)

@app.route("/enviar-recuperacao", methods=["POST"])
def enviar_recuperacao():
    email = request.form.get("email")
    usuario = Usuario.query.filter_by(email=email).first()
    
    if usuario:
        token = gerar_token(usuario.email)
        link = url_for('redefinir_senha', token=token, _external=True)
        msg = Message(subject="Redefinir senha - DevGym", 
                      sender=app.config['MAIL_USERNAME'], 
                      recipients=[email],
                      body=f"Olá {usuario.nome},\n\nClique no link abaixo para redefinir sua senha: {link}\n Link válido por 1 hora.")
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

@app.route('/treino/<int:treino_id>', methods=['GET', 'POST'])
def treinos_detalhes(treino_id):
    if 'usuario_id' not in session:
        return redirect('/login')
    
    treino = Treino.query.filter_by(id=treino_id,usuario_id=session['usuario_id']).first_or_404()
    
    if request.method == 'POST':
        nome_exercicio = request.form['nome_exercicio']
        novo_exercicio = Exercicio(nome=nome_exercicio, treino_id=treino_id)
        db.session.add(novo_exercicio)
        db.session.commit()
        return redirect(url_for('treinos_detalhes', treino_id=treino_id))

    exercicios = Exercicio.query.filter_by(treino_id=treino_id).all()

    # Calcular progresso
    total = len(exercicios)
    feitos = sum(1 for e in exercicios if e.concluido)
    progresso = int((feitos / total) * 100) if total > 0 else 0
    
    return render_template('treino_detalhes.html', treino=treino, exercicios=exercicios, progresso=progresso)

@app.route('/exercicio/<int:id>/concluir', methods=['POST'])
def concluir_exercicio(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    exercicio = Exercicio.query.get_or_404(id)
    treino = Treino.query.filter_by(id=exercicio.treino_id,usuario_id=session['usuario_id']).first_or_404()
    exercicio.concluido = not exercicio.concluido
    db.session.commit()
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

    db.session.delete(treino)  # 🔥 agora apaga de verdade
    db.session.commit()

    return redirect('/perfil')

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
    app.run(debug=True, host="0.0.0.0", port=5000)
