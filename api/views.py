from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum, F, Q, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from decimal import Decimal, InvalidOperation
from datetime import date
from django.db.models import ProtectedError


# --- IMPORTS LOCAIS ---
# Certifique-se que seus models estão nestes arquivos
from .models import (
    Cliente, ItemVenda, Produto, Venda, Orcamento, 
    PagamentoRecebido, PagamentoVenda
)
from .utils import calcular_juros
from .serializers import (
    ClienteSerializer, ProdutoSerializer, VendaSerializer, 
    OrcamentoSerializer, UserSerializer, PagamentoRecebidoSerializer,
    RelatorioDevedorSerializer
)

# -------------------------------------------------
# VIEWSETS (Lógica Principal CRUD)
# -------------------------------------------------

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

class ClienteViewSet(viewsets.ModelViewSet):
    # OTIMIZAÇÃO: O banco calcula o saldo automaticamente.
    # Nota: Usamos 'vendas__' (plural) conforme seu banco de dados.
    queryset = Cliente.objects.annotate(
        saldo_calculado=Coalesce(
            Sum('vendas__pagamento__valor', 
                filter=Q(vendas__pagamento__metodo='PRAZO', vendas__pagamento__status='PENDENTE')
            ),
            Decimal('0.00'),
            output_field=DecimalField()
        )
    ).order_by('nome')
    
    serializer_class = ClienteSerializer

    # AÇÃO DE RECEBER PAGAMENTO (Baixa automática FIFO)
    @action(detail=False, methods=['post'])
    def receber_pagamento(self, request):
        print(">>> INICIANDO PROCESSAMENTO DE PAGAMENTO...") 
        try:
            cliente_id = request.data.get('cliente_id')
            valor_raw = request.data.get('valor')
            metodo = request.data.get('metodo', 'DINHEIRO')
            
            if not cliente_id:
                return Response({"erro": "Cliente não informado."}, status=400)

            try:
                valor_str = str(valor_raw).replace(',', '.')
                valor_pago = Decimal(valor_str)
                if valor_pago <= 0: raise ValueError
            except (InvalidOperation, ValueError):
                return Response({"erro": "Valor inválido."}, status=400)

            with transaction.atomic():
                # 1. Registra Pagamento
                pagamento = PagamentoRecebido.objects.create(
                    cliente_id=cliente_id,
                    valor=valor_pago,
                    metodo=metodo,
                    data=date.today()
                )

                # 2. Busca dívidas pendentes (Mais antigas primeiro)
                dividas = PagamentoVenda.objects.filter(
                    venda__cliente_id=cliente_id,
                    metodo='PRAZO',
                    status='PENDENTE'
                ).order_by('venda__data')

                saldo_para_abater = valor_pago
                abatimentos = []

                for parcela in dividas:
                    if saldo_para_abater <= Decimal('0.00'): break
                    
                    if saldo_para_abater >= parcela.valor:
                        # Quita a parcela inteira
                        valor_da_parcela = parcela.valor
                        abatimentos.append(f"Venda #{parcela.venda.id} quitada (R$ {valor_da_parcela})")
                        saldo_para_abater -= valor_da_parcela
                        parcela.status = 'PAGO'
                        parcela.save()
                    else:
                        # Abate parcial
                        abatimentos.append(f"Venda #{parcela.venda.id} abatida parc. (R$ {saldo_para_abater})")
                        parcela.valor -= saldo_para_abater
                        parcela.save()
                        saldo_para_abater = Decimal('0.00')

                return Response({
                    "mensagem": "Pagamento registrado com sucesso!",
                    "id": pagamento.id,
                    "abatimentos": abatimentos,
                    "troco_ou_credito": saldo_para_abater
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            print(f"!!! ERRO CRÍTICO: {str(e)}")
            return Response({"erro": f"Erro interno: {str(e)}"}, status=500)

class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.exclude(nome__startswith="(EXCLUÍDO)").order_by('nome')
    serializer_class = ProdutoSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            # Tenta excluir de verdade (se nunca foi usado)
            self.perform_destroy(instance)
            return Response(status=status.HTTP_204_NO_CONTENT)
            
        except ProtectedError:
            # SE DER ERRO (já foi usado), fazemos a "Exclusão Visual"
            nome_antigo = instance.nome
            
            # 1. Marca o nome como excluído (mantendo o ID para referência)
            instance.nome = f"(EXCLUÍDO) {nome_antigo}"
            
            # 2. Zera o estoque para ninguém vender mais por engano
            if hasattr(instance, 'estoque'): instance.estoque = 0
            elif hasattr(instance, 'quantidade'): instance.quantidade = 0
            
            instance.save()
            
            # Retorna 200 (Sucesso) para o Frontend remover da tela
            return Response(
                {"mensagem": "Produto marcado como EXCLUÍDO no histórico."},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response({"erro": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class VendaViewSet(viewsets.ModelViewSet):
    queryset = Venda.objects.all().order_by('-data')
    serializer_class = VendaSerializer

    # 1. CANCELAR VENDA INTEIRA (Estorna estoque e cancela dívida)
    @action(detail=True, methods=['post'])
    def cancelar_venda(self, request, pk=None):
        venda = self.get_object()
        
        if getattr(venda, 'status', '') == 'CANCELADA':
             return Response({"erro": "Esta venda já foi cancelada."}, status=400)

        try:
            with transaction.atomic():
                # A. Devolve estoque
                for item in venda.itens.all():
                    produto = item.produto
                    if hasattr(produto, 'estoque'): produto.estoque += item.quantidade
                    elif hasattr(produto, 'quantidade'): produto.quantidade += item.quantidade
                    produto.save()

                # B. Cancela pagamentos (Tenta achar a relação de pagamentos)
                pagamentos = getattr(venda, 'pagamento', None) or getattr(venda, 'pagamentovenda_set', None)
                if pagamentos:
                    pagamentos.all().update(status='CANCELADO')

                # C. Apaga a venda
                venda.delete()

            return Response({"mensagem": "Venda cancelada com sucesso!"})

        except Exception as e:
            print(f"ERRO AO CANCELAR: {str(e)}") 
            return Response({"erro": f"Erro interno: {str(e)}"}, status=500)

    # 2. REMOVER APENAS UM ITEM (Atualiza total e dívida)
    @action(detail=True, methods=['post'])
    def remover_item(self, request, pk=None):
        venda = self.get_object()
        item_id = request.data.get('item_id')

        print(f"--- REMOVENDO ITEM DA VENDA #{venda.id} ---")

        try:
            item = ItemVenda.objects.get(id=item_id, venda=venda)
            valor_removido = item.valorFinal

            with transaction.atomic():
                # 1. Devolve ao estoque
                produto = item.produto
                if hasattr(produto, 'estoque'): produto.estoque += item.quantidade
                elif hasattr(produto, 'quantidade'): produto.quantidade += item.quantidade
                produto.save()

                # 2. Remove o item
                item.delete()
                
                # 3. Atualiza totais da VENDA
                venda.subtotal -= valor_removido
                venda.total -= valor_removido
                venda.save()

                # 4. ATUALIZA A DÍVIDA (PagamentoVenda)
                # Busca parcelas pendentes que NÃO sejam dinheiro (Prazo, Fiado, etc)
                dividas = PagamentoVenda.objects.filter(
                    venda=venda, 
                    status='PENDENTE'
                ).exclude(metodo='DINHEIRO')
                
                valor_para_abater = valor_removido

                for parcela in dividas:
                    if valor_para_abater <= 0: break
                    
                    if parcela.valor > valor_para_abater:
                        parcela.valor -= valor_para_abater
                        parcela.save()
                        valor_para_abater = 0
                    else:
                        valor_para_abater -= parcela.valor
                        parcela.delete() # Zera a parcela apagando ela

            return Response({"mensagem": "Item removido e dívida atualizada!"})
        except Exception as e:
            print(f"ERRO AO REMOVER ITEM: {str(e)}")
            return Response({"erro": str(e)}, status=500)


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
        # 1. Mapa de pagamentos (Histórico Geral)
        total_pago_por_cliente = PagamentoRecebido.objects.values('cliente_id') \
            .annotate(total_pago=Sum('valor')).order_by()
        pago_map = {item['cliente_id']: item['total_pago'] for item in total_pago_por_cliente}

        # 2. Mapa de Dívidas (O que está PENDENTE hoje)
        divida_map = {}
        # Busca todas as parcelas pendentes de vendas a prazo
        parcelas_pendentes = PagamentoVenda.objects.filter(
            metodo='PRAZO', 
            status='PENDENTE'
        ).select_related('venda')

        for parcela in parcelas_pendentes:
            cliente_id = parcela.venda.cliente_id
            valor_atual = parcela.valor
            
            if cliente_id not in divida_map:
                divida_map[cliente_id] = Decimal('0.00')
            divida_map[cliente_id] += valor_atual

        # 3. Monta lista final
        clientes = Cliente.objects.all()
        clientes_devedores = []

        for cliente in clientes:
            divida_atual = divida_map.get(cliente.id, Decimal('0.00'))
            total_historico = pago_map.get(cliente.id, Decimal('0.00'))
            
            # Mostra quem deve mais de 1 centavo
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
        mes_atual = hoje.month
        ano_atual = hoje.year

        vendas_hoje = Venda.objects.filter(
            data__year=ano_atual, data__month=mes_atual, data__day=hoje.day
        ).aggregate(Sum('total'))['total__sum'] or 0

        vendas_mes = Venda.objects.filter(
            data__year=ano_atual, data__month=mes_atual
        )
        total_mes = vendas_mes.aggregate(Sum('total'))['total__sum'] or 0
        qtd_vendas_mes = vendas_mes.count()
        total_clientes = Cliente.objects.count()

        top_produtos = ItemVenda.objects.values('nome') \
            .annotate(total_vendido=Sum('quantidade')) \
            .order_by('-total_vendido')[:5]

        total_a_receber = PagamentoVenda.objects.filter(
            metodo='PRAZO', status='PENDENTE'
        ).aggregate(Sum('valor'))['valor__sum'] or 0

        return Response({
            "vendas_hoje": vendas_hoje,
            "vendas_mes": total_mes,
            "qtd_vendas_mes": qtd_vendas_mes,
            "total_clientes": total_clientes,
            "contas_a_receber_total": total_a_receber,
            "top_produtos": list(top_produtos)
        })