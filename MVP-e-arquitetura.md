# Arquitetura do Delta Mapas

Revisão: 14/10/2026. Este documento substitui a proposta inicial com organizações.

## Decisões confirmadas

- Aplicação principal em Rust; a implementação antiga em Django foi removida.
- Backend e processamento em Rust, produção em uma VM da OCI.
- Login individual: cada conta é um tenant, sem cadastro de empresa, membros ou equipes.
- Análises sob demanda e acompanhamento semanal opcional por talhão.

## Jornada

Criar conta ou receber acesso ao piloto, entrar, cadastrar propriedade e talhão,
importar GeoJSON ou ZIP do CAR, selecionar período e limite de nuvens, solicitar NDVI,
acompanhar processamento e consultar mapa, estatísticas e exportações no histórico.

O resultado informa origem, data da cena e cobertura válida. Nuvens de uma tile
não equivalem a nuvens do talhão. Falhas sem resultado não consomem a análise reservada.

## Arquitetura implementada nesta etapa

Um executável Rust com modos `serve`, `worker`, `migrate` e `create-user`, além das
ferramentas locais de processamento. A interface React/TypeScript é compilada pelo Vite e embutida no
servidor Axum. O Docker executa o build do frontend antes de compilar o Rust.

```text
Navegador -> Caddy/HTTPS -> Servidor Rust
                              |
                        PostgreSQL/PostGIS
                          dados + fila
                              |
                         Worker Rust -> Copernicus
                              |
                        Arquivos privados
```

Servidor, worker e migrations usam a mesma imagem. Há quatro serviços permanentes
na implantação de produção: proxy, servidor, worker e banco. Os arquivos ficam em
volume persistente privado, com downloads autorizados pelo servidor.

## Modelo de dados

| Entidade | Responsabilidade |
| --- | --- |
| Conta | Identidade, senha protegida e limite de uso |
| Sessão | Autenticação, CSRF e expiração |
| Propriedade | Agrupamento de talhões do usuário |
| Talhão | Geometria, área, propriedade e revisão |
| Análise | Snapshot da área, período, origem, fila, tentativas e resultado |

Propriedades, talhões e análises possuem `user_id`. Relações usam chaves compostas
para não misturar donos. Rotas filtram por usuário; RLS com FORCE reforça o isolamento
no banco. O contexto de usuário é restrito à transação, sem persistir entre conexões.

O worker possui contexto interno para trabalhar nas contas. O aplicativo não aceita
uma role PostgreSQL com SUPERUSER ou BYPASSRLS. Usuários finais não recebem acesso SQL.

## Consistência

- Reserva de uso e criação da tarefa na mesma transação, com bloqueio da conta.
- Idempotência por conta e chave de solicitação; conflito quando a chave muda de conteúdo.
- Snapshot imutável de geometria/revisão: editar o talhão não altera uma análise solicitada.
- Aquisição transacional de tarefas, posse temporária e heartbeat.
- Recuperação de tarefas interrompidas e até três tentativas com espera progressiva.
- Produtos em diretório próprio por tentativa, sem sobrescrever outra tentativa.
- Conclusão e consumo na mesma transação; atualização condicionada à posse atual.
- Falha definitiva libera a reserva uma vez. Conclusão não duplica o consumo.

O limite atual é uma franquia inicial de dez análises por conta para o piloto.
Ainda não existe assinatura paga, renovação mensal ou reutilização por cena entre
solicitações com chaves diferentes.

## Monitoramento automático

A migration 0003 adiciona configurações de acompanhamento e alertas, com RLS.
O worker verifica agendamentos a cada minuto; um lock transacional do agendador
impede concorrência entre instâncias, e a conta é bloqueada para reservar uso.
Cada pedido tem uma chave idempotente por talhão, configuração e data. Não há
pedidos automáticos simultâneos para o mesmo talhão. Sem saldo, nova verificação
ocorre em uma hora. Após o pedido, a próxima execução é agendada para sete dias.

A configuração registra cultura, fase atual, período da safra e queda mínima absoluta de NDVI.
Pedidos usam somente satélite, janela dos últimos sete dias completos em UTC e
limite de 40% de nuvens na cena. A cobertura válida do talhão é avaliada à parte.
Ao finalizar, a data real da cena fica registrada no banco. Comparações usam a
mesma revisão de geometria e geração de configuração, datas distintas dentro da
safra, intervalo máximo de 30 dias e cobertura válida de pelo menos 90% em ambas.
Conclusão, alerta e consumo são persistidos na mesma transação. Alertas ficam na
interface para conferência. Cultura não altera os limiares automaticamente;
a fase é informada pelo usuário, com alertas suspensos na maturação e colheita.
Modelos automáticos de fase fenológica ficam para uma evolução.

## Operação

Compose local inclui demonstrações sintéticas explicitamente identificadas e cadastro
público. Compose de produção exige HTTPS, fecha cadastro público e desativa demonstrações.
A aplicação de migrations é uma etapa anterior ao servidor e ao worker.

A VM deve consumir imagens de release prontas. Antes de implantar: confirmar CPU/ARM64
ou x86_64, dimensionar memória e disco, configurar domínio, credenciais de imagens,
backup externo e restauração ensaiada. Uma VM não fornece alta disponibilidade.

## Entregas ainda necessárias

- Confirmar condições comerciais do provedor e ampliar cobertura de áreas na borda de tiles.
- Desenho de áreas no mapa; atualmente há importação de GeoJSON/ZIP do CAR e prévia do contorno.
  O CAR importa o limite do imóvel inteiro, não uma segmentação automática em talhões.
- Recuperação de senha e verificação de e-mail antes do autocadastro público em produção.
- Planos, pagamentos e renovação dos limites.
- Backup/restauração, coleta de arquivos órfãos e observabilidade operacional.
- Testar ARM64 e implantar na VM OCI. Nenhuma publicação foi realizada nesta etapa.

## Critérios de aceite desta etapa

- Login e cadastro de áreas funcionam na interface.
- Duas contas não conseguem ler, modificar ou baixar dados uma da outra.
- Uma tarefa de demonstração atravessa a fila e gera produtos privados.
- Repetição de chave não duplica reserva; concorrência não ultrapassa a franquia.
- Interrupção de worker pode ser recuperada; falha definitiva libera uso reservado.
- Edição de geometria preserva o snapshot já solicitado.
- Código, testes e implantação local usam PostgreSQL com usuário sem privilégios de bypass.


### Referência espacial implementada

Cadastro PostGIS e snapshots de jobs: SIRGAS 2000/EPSG:4674. Navegador e Process API:
WGS84/EPSG:4326, convertidos na fronteira. Novos GeoTIFFs, PNGs e mapas dos PDFs:
SIRGAS 2000/UTM com fuso automático e pixels de 10 m, reamostragem por vizinho mais próximo.
O NDVI e suas estatísticas são calculados na grade original, explicitada nos metadados.
A migration 0002 transforma o cadastro existente; produtos históricos permanecem intactos.
