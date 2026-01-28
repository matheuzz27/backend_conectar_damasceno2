# api/models.py V3 (Completo)

from django.db import models
from django.contrib.auth.models import User

# --- LISTAS DE OPÇÕES (Predefinidas) ---

# 1. Opções para VENDA (Aceita "PRAZO/Fiado")
OPCOES_PAGAMENTO_VENDA = [
    ('DINHEIRO', 'Dinheiro'),
    ('PIX', 'Pix'),
    ('CARTÃO', 'Cartão'),
    ('PRAZO', 'A Prazo (Fiado)'),
]

# 2. Opções para RECEBIMENTO DE DÍVIDA (NÃO aceita "PRAZO")
# (Lógica: Não se paga uma dívida criando outra dívida)
OPCOES_PAGAMENTO_RECEBIDO = [
    ('DINHEIRO', 'Dinheiro'),
    ('PIX', 'Pix'),
    ('CARTÃO', 'Cartão'),
]

# -------------------------------------------------
# MODELOS
# -------------------------------------------------

class Cliente(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    endereco = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.nome

class Produto(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    # DecimalField é melhor para dinheiro que FloatField
    precoCompra = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    precoVenda = models.DecimalField(max_digits=10, decimal_places=2)
    tem_preco_prazo = models.BooleanField(default=False, verbose_name="Tem Preço a Prazo?")
    preco_prazo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Preço a Prazo")

    def __str__(self):
        return self.nome

class Venda(models.Model):
    # Relacionamentos
    cliente = models.ForeignKey(Cliente, related_name='vendas', on_delete=models.PROTECT)
    vendedor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Dados da Venda
    data = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    desconto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"Venda #{self.id} - {self.cliente.nome}"

class ItemVenda(models.Model):
    venda = models.ForeignKey(Venda, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    
    # Snapshot dos dados do produto no momento da venda
    nome = models.CharField(max_length=255)
    quantidade = models.DecimalField(max_digits=10, decimal_places=3)
    valorUnitario = models.DecimalField(max_digits=10, decimal_places=2)
    valorFinal = models.DecimalField(max_digits=10, decimal_places=2)
    precoCompra = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantidade} x {self.nome}"

class PagamentoVenda(models.Model):
    venda = models.ForeignKey(Venda, related_name='pagamento', on_delete=models.CASCADE)
    
    # Usa as opções COM PRAZO
    metodo = models.CharField(
        max_length=50, 
        choices=OPCOES_PAGAMENTO_VENDA, 
        default='DINHEIRO'
    )
    
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default='PAGO') 

class Orcamento(models.Model):
    cliente = models.ForeignKey(Cliente, related_name='orcamentos', on_delete=models.PROTECT)
    vendedor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    data = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default='PENDENTE')

class ItemOrcamento(models.Model):
    orcamento = models.ForeignKey(Orcamento, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    
    nome = models.CharField(max_length=255)
    quantidade = models.DecimalField(max_digits=10, decimal_places=3)
    valorUnitario = models.DecimalField(max_digits=10, decimal_places=2)
    valorFinal = models.DecimalField(max_digits=10, decimal_places=2)
    precoCompra = models.DecimalField(max_digits=10, decimal_places=2)

class PagamentoRecebido(models.Model):
    cliente = models.ForeignKey(Cliente, related_name='pagamentos_recebidos', on_delete=models.PROTECT)
    data = models.DateTimeField(auto_now_add=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Usa as opções SEM PRAZO
    metodo = models.CharField(
        max_length=50, 
        choices=OPCOES_PAGAMENTO_RECEBIDO, 
        default='DINHEIRO'
    )

    def __str__(self):
        return f"Pagamento de {self.cliente.nome} - R${self.valor}"