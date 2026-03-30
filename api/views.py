# api/views.py
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum, F, Q, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from decimal import Decimal, InvalidOperation
from datetime import date
from django.db.models import ProtectedError

from .models import (
    Cliente, ItemVenda, Produto, Venda, Orcamento, 
    PagamentoRecebido, PagamentoVenda
)
from .serializers import (
    ClienteSerializer, ProdutoSerializer, VendaSerializer, 
    OrcamentoSerializer, UserSerializer, PagamentoRecebidoSerializer,
    RelatorioDevedorSerializer
)

# -------------------------------------------------
# 🛡️ PAINEL SUPER ADMIN (Botão do Pânico)
# -------------------------------------------------
class SuperAdminView(APIView):
    # Só permite acesso se o usuário for IsAuthenticated E for Superuser (is_staff/is_superuser)
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        if not request.user.is_superuser:
            return Response({"erro": "Acesso Negado. Apenas o dono do sistema pode executar esta ação."}, status=403)

        acao = request.data.get('acao')

        try:
            with transaction.atomic():
                if acao == 'ZERAR_FINANCEIRO':
                    PagamentoRecebido.objects.all().delete()
                    Venda.objects.all().delete()
                    mensagem = "Vendas e Pagamentos apagados com sucesso!"
                
                elif acao == 'ZERAR_CLIENTES':
                    Cliente.objects.all().delete()
                    mensagem = "Todos os clientes foram apagados!"
                
                elif acao == 'ZERAR_PRODUTOS':
                    Produto.objects.all().delete()
                    mensagem = "Todos os produtos foram apagados!"
                
                elif acao == 'RESET_FABRICA':
                    PagamentoRecebido.objects.all().delete()
                    Venda.objects.all().delete()
                    Orcamento.objects.all().delete()
                    Produto.objects.all().delete()
                    Cliente.objects.all().delete()
                    mensagem = "RESET TOTAL CONCLUÍDO. O sistema está limpo como novo!"
                
                else:
                    return Response({"erro": "Ação desconhecida."}, status=400)

            return Response({"mensagem": mensagem}, status=200)

        except ProtectedError:
            return Response({"erro": "Não é possível apagar registros que estão sendo usados (Ex: Apagar cliente sem apagar as vendas dele antes)."}, status=400)
        except Exception as e:
            return Response({"erro": f"Falha ao executar ação nuclear: {str(e)}"}, status=500)


# -------------------------------------------------
# VIEWSETS
# -------------------------------------------------
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

class ClienteViewSet(viewsets.ModelViewSet):
    queryset = Cliente.objects.all().order_by('nome')
    serializer_class = ClienteSerializer

    @action(detail=False, methods=['post'])
    def receber_pagamento(self, request):
        try:
            cliente_id = request.data.get('cliente_id')
            valor_raw = request.data.get('valor')
            metodo = request.data.get('metodo', 'DINHEIRO')
            
            if not cliente_id:
                return Response({"erro": "Cliente não informado."}, status=400)

            try:
                valor_pago = Decimal(str(valor_raw).replace(',', '.'))
                if valor_pago <= 0: raise ValueError
            except (InvalidOperation, ValueError):
                return Response({"erro": "Valor inválido."}, status=400)

            with transaction.atomic():
                pagamento = PagamentoRecebido.objects.create(
                    cliente_id=cliente_id, valor=valor_pago, metodo=metodo, data=date.today()
                )

                dividas = PagamentoVenda.objects.filter(
                    venda__cliente_id=cliente_id, metodo='PRAZO', status='PENDENTE'
                ).order_by('venda__data')

                saldo_para_abater = valor_pago
                abatimentos = []

                for parcela in dividas:
                    if saldo_para_abater <= Decimal('0.00'): break
                    
                    # 📈 Aplica a inteligência de Juros na hora de pagar!
                    valor_divida_atual = parcela.valor_com_juros 

                    if saldo_para_abater >= valor_divida_atual:
                        abatimentos.append(f"Venda #{parcela.venda.id} quitada (R$ {valor_divida_atual})")
                        saldo_para_abater -= valor_divida_atual
                        parcela.status = 'PAGO'
                        # Atualiza o valor para o valor final com juros no banco
                        parcela.valor = valor_divida_atual 
                        parcela.save()
                    else:
                        abatimentos.append(f"Venda #{parcela.venda.id} abatida parc. (R$ {saldo_para_abater})")
                        # Se abateu só um pedaço, atualizamos a dívida considerando os juros
                        parcela.valor = valor_divida_atual - saldo_para_abater
                        parcela.save()
                        saldo_para_abater = Decimal('0.00')

                return Response({
                    "mensagem": "Pagamento registrado com sucesso!",
                    "id": pagamento.id, "abatimentos": abatimentos, "troco": saldo_para_abater
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"erro": f"Erro interno: {str(e)}"}, status=500)

class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.exclude(nome__startswith="(EXCLUÍDO)").order_by('nome')
    serializer_class = ProdutoSerializer

    # 🗑️ EXCLUSÃO PADRÃO (Botão da Lixeirinha)
    def destroy(self, request, *args, **kwargs):
        venda = self.get_object()
        try:
            with transaction.atomic():
                # O Django já usa CASCADE e apaga os itens e pagamentos vinculados automaticamente
                venda.delete()
            # Retornamos 200 OK com JSON para o React não travar!
            return Response({"mensagem": "Venda excluída com sucesso!"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"erro": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 🚫 CANCELAR VENDA INTEIRA (Botão Vermelho Grande)
    @action(detail=True, methods=['post'])
    def cancelar_venda(self, request, pk=None):
        venda = self.get_object()
        try:
            with transaction.atomic():
                # Se no futuro você tiver estoque, a devolução entra aqui. 
                # Por enquanto, só apagamos a venda para limpar as contas do cliente.
                venda.delete()
            return Response({"mensagem": "Venda cancelada e excluída com sucesso!"}, status=status.HTTP_200_OK)
        except Exception as e:
            print(f"ERRO AO CANCELAR: {str(e)}") 
            return Response({"erro": f"Erro interno: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ➖ REMOVER APENAS UM ITEM DA VENDA (Lixeirinha do Item)
    @action(detail=True, methods=['post', 'delete'])
    def remover_item(self, request, pk=None):
        venda = self.get_object()
        # Aceita o ID do item tanto por JSON (post) quanto por URL/Query (delete)
        item_id = request.data.get('item_id') or request.query_params.get('item_id')

        try:
            item = ItemVenda.objects.get(id=item_id, venda=venda)
            valor_removido = item.valorFinal

            with transaction.atomic():
                item.delete()
                
                # Atualiza os totais da Venda Principal
                venda.subtotal -= valor_removido
                venda.total -= valor_removido
                venda.save()

                # Se a venda ficou zerada, apaga ela inteira
                if venda.total <= 0:
                    venda.delete()
                    return Response({"mensagem": "Venda inteira excluída pois ficou sem itens!"}, status=status.HTTP_200_OK)

                # Abate a dívida do cliente (se foi a prazo)
                dividas = PagamentoVenda.objects.filter(venda=venda, status='PENDENTE').exclude(metodo='DINHEIRO')
                valor_para_abater = valor_removido

                for parcela in dividas:
                    if valor_para_abater <= 0: break
                    if parcela.valor > valor_para_abater:
                        parcela.valor -= valor_para_abater
                        parcela.save()
                        valor_para_abater = 0
                    else:
                        valor_para_abater -= parcela.valor
                        parcela.delete()

            return Response({"mensagem": "Item removido com sucesso!"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"erro": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class VendaViewSet(viewsets.ModelViewSet):
    queryset = Venda.objects.all().order_by('-data')
    serializer_class = VendaSerializer

   # ⚡ OTIMIZAÇÃO FLASH: Salvando a venda inteira em 1 viagem ao Banco
    def create(self, request, *args, **kwargs):
        data = request.data
        try:
            with transaction.atomic():
                # 1. Cria o Cabeçalho da Venda
                venda = Venda.objects.create(
                    cliente_id=data.get('cliente') or data.get('cliente_id'),
                    vendedor=request.user if request.user.is_authenticated else None,
                    subtotal=data.get('subtotal', 0),
                    desconto=data.get('desconto', 0),
                    total=data.get('total', 0)
                )

                # 2. Empacota os itens (Bulk Create)
                itens_array = data.get('itens', [])
                
                # 🛡️ BLINDAGEM: Busca os dados reais dos produtos no banco (Evita erro de 'null')
                produto_ids = [item.get('produto') or item.get('produto_id') for item in itens_array]
                produtos_banco = {p.id: p for p in Produto.objects.filter(id__in=produto_ids)}

                itens_para_salvar = []
                for item in itens_array:
                    p_id = item.get('produto') or item.get('produto_id')
                    produto_real = produtos_banco.get(p_id)
                    
                    # Se o Frontend não mandou o nome, o Backend pega do banco automaticamente!
                    nome_seguro = item.get('nome') or item.get('produto_nome') or (produto_real.nome if produto_real else 'Produto Desconhecido')
                    preco_compra_seguro = item.get('precoCompra') or (produto_real.precoCompra if produto_real else 0)

                    itens_para_salvar.append(ItemVenda(
                        venda=venda, 
                        produto_id=p_id, 
                        nome=nome_seguro,
                        quantidade=item.get('quantidade', 1), 
                        valorUnitario=item.get('valorUnitario', item.get('preco_venda', 0)),
                        valorFinal=item.get('valorFinal', item.get('total', 0)), 
                        precoCompra=preco_compra_seguro
                    ))
                ItemVenda.objects.bulk_create(itens_para_salvar)

                # 3. Empacota os pagamentos (Bulk Create)
                pgtos_array = data.get('pagamento', [])
                pgtos_para_salvar = []
                for pg in pgtos_array:
                    pgtos_para_salvar.append(PagamentoVenda(
                        venda=venda, 
                        metodo=pg.get('metodo'), 
                        valor=pg.get('valor'),
                        status=pg.get('status', 'PAGO' if pg.get('metodo') != 'PRAZO' else 'PENDENTE')
                    ))
                PagamentoVenda.objects.bulk_create(pgtos_para_salvar)

            return Response(VendaSerializer(venda).data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response({"erro": f"Erro ao salvar: {str(e)}"}, status=500)

class OrcamentoViewSet(viewsets.ModelViewSet):
    queryset = Orcamento.objects.all().order_by('-data')
    serializer_class = OrcamentoSerializer

class PagamentoRecebidoViewSet(viewsets.ModelViewSet):
    queryset = PagamentoRecebido.objects.all().order_by('-data')
    serializer_class = PagamentoRecebidoSerializer

# -------------------------------------------------
# RELATÓRIOS E DASHBOARD
# -------------------------------------------------
class RelatorioDevedoresView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        total_pago_por_cliente = PagamentoRecebido.objects.values('cliente_id').annotate(total_pago=Sum('valor')).order_by()
        pago_map = {item['cliente_id']: item['total_pago'] for item in total_pago_por_cliente}

        divida_map = {}
        # ⚡ Usando select_related para evitar lentidão N+1
        parcelas_pendentes = PagamentoVenda.objects.filter(
            metodo='PRAZO', status='PENDENTE'
        ).select_related('venda')

        for parcela in parcelas_pendentes:
            cliente_id = parcela.venda.cliente_id
            
            # 📈 A mágica acontece aqui: Ele puxa o valor já calculado com juros do model!
            valor_atual = parcela.valor_com_juros 
            
            if cliente_id not in divida_map:
                divida_map[cliente_id] = Decimal('0.00')
            divida_map[cliente_id] += valor_atual

        clientes = Cliente.objects.all()
        clientes_devedores = []

        for cliente in clientes:
            divida_atual = divida_map.get(cliente.id, Decimal('0.00'))
            total_historico = pago_map.get(cliente.id, Decimal('0.00'))
            
            if divida_atual > Decimal('0.01'):
                cliente.saldo_devedor_atual = divida_atual
                cliente.divida_bruta_com_juros = divida_atual
                cliente.total_pago = total_historico
                clientes_devedores.append(cliente)
        
        clientes_devedores.sort(key=lambda x: x.saldo_devedor_atual, reverse=True)
        serializer = RelatorioDevedorSerializer(clientes_devedores, many=True)
        return Response(serializer.data)

class DashboardView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        hoje = date.today()
        vendas_hoje = Venda.objects.filter(data__date=hoje).aggregate(Sum('total'))['total__sum'] or 0
        vendas_mes = Venda.objects.filter(data__year=hoje.year, data__month=hoje.month)
        
        # Puxa os dados formatados
        return Response({
            "vendas_hoje": vendas_hoje,
            "vendas_mes": vendas_mes.aggregate(Sum('total'))['total__sum'] or 0,
            "qtd_vendas_mes": vendas_mes.count(),
            "total_clientes": Cliente.objects.count(),
            # Exibe a soma real das contas, mas sem calcular juros na tela inicial para ser rápido
            "contas_a_receber_total": PagamentoVenda.objects.filter(metodo='PRAZO', status='PENDENTE').aggregate(Sum('valor'))['valor__sum'] or 0,
            "top_produtos": list(ItemVenda.objects.values('nome').annotate(total_vendido=Sum('quantidade')).order_by('-total_vendido')[:5])
        })