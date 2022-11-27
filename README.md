# **Chiru Aldeano**
[![CodeFactor](https://www.codefactor.io/repository/github/chirusxs/chiru-aldeano/badge)](https://www.codefactor.io/repository/github/chirusxs/chiru-aldeano)
[![Discord](https://img.shields.io/discord/714753410985099284?color=0FAE6E&label=Discord)](https://discord.gg/ZC8shhpSkf)
[![CI](https://github.com/chirusxs/Chiru-Aldeano/actions/workflows/ci.yml/badge.svg)](https://github.com/chirusxs/Chiru-Aldeano/actions/workflows/ci.yml)

## Características principales
* La posibilidad de revisar el estado del servidor de Minecraft de la comunidad
* Un sistema de economía basado en esmeraldas, con objetos, herramientas y más
* Comandos de diversión variados para interactuar en los canales de Discord

## Información de contacto
* [Discord Server](https://discord.gg/ZC8shhpSkf)
* E-mail: `soporte@chirusxs.net`

## Tecnologías
- [discord.py](https://github.com/Rapptz/discord.py)
- [Cython](https://cython.org/)
- [OpenCV](https://opencv.org/) + [Numpy](https://numpy.org/)
- websockets
### Arquitectura
Chiru Aldeano está separado en dos componentes; "Karen" y los clusters. Un "cluster" es un grupo de shards (websockets conectados a Discord).
Debido a como Chiru Aldeano funciona, los clusters necesitan estar comunicados entre sí, que es lo que "Karen" hace posible mediante el uso de websockets.
El bot está dockerizado y su arquitectura permite cambiar de escalas manteniendo estabilidad y un desarrollo sencillo.

## Reconocimientos originales / Original acknowledgments
- [Iapetus-11](https://github.com/Iapetus-11) - Dueño, creador y principal mantenedor del bot / Owner, creator and main maintainer of the bot
- El bot puede propocionar una lista completa de los créditos originales en Discord

## Reconocimientos (Pendiente de agregar)
- Puedes ver la lista de contribuidores en este repositorio y también puedes ver una lista de créditos del fork (diseñadores de los nuevos emojis propios del fork, desarrolladores de código totalmente nuevo, etc) proporcionada por el bot en Discord

## [Privacy Policy](PRIVACY-POLICY.md)
