# **Chiru Aldeano**
[![CodeFactor](https://www.codefactor.io/repository/github/chirusxs/chiru-aldeano/badge)](https://www.codefactor.io/repository/github/chirusxs/chiru-aldeano)
[![Discord](https://img.shields.io/discord/714753410985099284?color=0FAE6E&label=Discord)](https://discord.gg/ZC8shhpSkf)
[![CI](https://github.com/chirusxs/Chiru-Aldeano/actions/workflows/ci.yml/badge.svg)](https://github.com/chirusxs/Chiru-Aldeano/actions/workflows/ci.yml)

## Notable Features
* Ability to ping / check the status of the CHIRUSXS Minecraft server
* Expansive emerald-based economy system
* Tons of customization and configuration options

## Contact Information
* [Discord Server](https://discord.gg/ZC8shhpSkf)
* E-mail: `soporte@chirusxs.net`

## Technologies
- [discord.py](https://github.com/Rapptz/discord.py)
- [Cython](https://cython.org/)
- [OpenCV](https://opencv.org/) + [Numpy](https://numpy.org/)
- websockets
### Architecture
Chiru Aldeano is separated into two components; Karen and the clusters. A "cluster" is a group of shards (websockets connected to Discord in this case).
Due to the nature of Chiru Aldeano, these clusters need to share state and communicate, which is what Karen facilitates via the use of websockets.
The bot is dockerized and this architecture allows scaling while maintaining functionality and easy development.

## Acknowledgments
- [Iapetus-11](https://github.com/Iapetus-11), the creator of the project

## [Privacy Policy](PRIVACY-POLICY.md)
