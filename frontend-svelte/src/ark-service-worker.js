import {
  IndexedDBWalletRepository,
  IndexedDBContractRepository,
  MessageBus,
  WalletMessageHandler,
} from '@arkade-os/sdk';

const walletRepository = new IndexedDBWalletRepository();
const contractRepository = new IndexedDBContractRepository();

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    event.waitUntil(self.skipWaiting());
  }
});

const worker = new MessageBus(walletRepository, contractRepository, {
  messageHandlers: [new WalletMessageHandler()],
  tickIntervalMs: 5000,
});
worker.start().catch(console.error);

self.addEventListener('install', () => {
  self.skipWaiting();
  console.log('Arkana service worker installed');
});

self.addEventListener('activate', () => {
  self.clients.claim();
});
