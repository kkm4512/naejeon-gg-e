import { Module } from '@nestjs/common';
import { GamesModule } from './games/games.module';
import { FirebaseModule } from './firebase/firebase.module';

@Module({
  imports: [FirebaseModule, GamesModule],
})
export class AppModule {}
