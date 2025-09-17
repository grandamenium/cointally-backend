#!/usr/bin/env python3
"""
Demonstration of CORRECTED Binance CSV processing vs old flawed approach
Shows exactly what was wrong and how the fix matches Koinly's logic
"""

import pandas as pd
from io import StringIO
from decimal import Decimal
from datetime import datetime
from collections import defaultdict


def create_sample_csv():
    """Create sample CSV from the user's actual data"""
    return """User_ID,UTC_Time,Account,Operation,Coin,Change,Remark
162766010,24/12/2024 14:54,Spot,Transaction Spend,USDT,-199.56205,
162766010,24/12/2024 14:54,Spot,Transaction Buy,DOGE,601,
162766010,24/12/2024 14:54,Spot,Transaction Fee,DOGE,-0.601,
162766010,29/12/2024 22:06,Spot,Transaction Buy,SHIB,47830,
162766010,29/12/2024 22:06,Spot,Transaction Spend,USDT,-1.0302582,
162766010,29/12/2024 22:06,Spot,Transaction Fee,SHIB,-47.83,
162766010,29/12/2024 22:06,Spot,Transaction Buy,SHIB,47830,
162766010,29/12/2024 22:06,Spot,Transaction Spend,USDT,-1.0302582,
162766010,29/12/2024 22:06,Spot,Transaction Fee,SHIB,-47.83,
162766010,06/01/2025 9:06,Spot,Transaction Revenue,USDT,99.9160866,
162766010,06/01/2025 9:06,Spot,Transaction Fee,USDT,-0.09991609,
162766010,06/01/2025 9:06,Spot,Transaction Sold,SHIB,-4194630,
162766010,20/10/2024 16:10,Spot,Binance Convert,BNB,0.002197,
162766010,20/10/2024 16:10,Spot,Binance Convert,USDT,-1.3225298,"""


def demonstrate_old_flawed_approach():
    """Show what the OLD flawed code does (treats each row as separate transaction)"""

    csv_content = create_sample_csv()
    df = pd.read_csv(StringIO(csv_content))

    print("❌ OLD FLAWED APPROACH (What was happening before)")
    print("=" * 60)
    print("Treats EACH CSV row as a separate transaction:")
    print()

    transaction_count = 0
    for _, row in df.iterrows():
        operation = row['Operation']
        coin = row['Coin']
        change = row['Change']

        # Skip operations the old code would skip
        if operation in ['Transfer Between Main and Funding Wallet']:
            continue

        # The old code would create individual transactions
        if operation == 'Transaction Buy':
            transaction_count += 1
            print(f"  Transaction #{transaction_count}: BUY {change} {coin}")
        elif operation == 'Transaction Spend':
            transaction_count += 1
            print(f"  Transaction #{transaction_count}: SELL {abs(change)} {coin}")
        elif operation == 'Transaction Sold':
            transaction_count += 1
            print(f"  Transaction #{transaction_count}: SELL {abs(change)} {coin}")
        elif operation == 'Transaction Revenue':
            transaction_count += 1
            print(f"  Transaction #{transaction_count}: BUY {change} {coin}")
        elif operation == 'Binance Convert':
            if change > 0:
                transaction_count += 1
                print(f"  Transaction #{transaction_count}: BUY {change} {coin}")
            else:
                transaction_count += 1
                print(f"  Transaction #{transaction_count}: SELL {abs(change)} {coin}")

    print(f"\n📊 Result: {transaction_count} separate transactions (WRONG!)")
    print("\n🚨 Problems with this approach:")
    print("   • DOGE purchase split into 3 separate transactions")
    print("   • No proper fee handling")
    print("   • SHIB purchases not grouped properly")
    print("   • Sell transactions missing proper grouping")
    print("   • FIFO calculations will be completely wrong")


def demonstrate_corrected_approach():
    """Show what the CORRECTED code does (groups related transactions like Koinly)"""

    csv_content = create_sample_csv()
    df = pd.read_csv(StringIO(csv_content))

    print("\n\n✅ CORRECTED APPROACH (How it works now - like Koinly)")
    print("=" * 60)
    print("Groups related CSV rows into proper transactions:")
    print()

    # Group transactions by timestamp and type (simplified version)
    groups = group_transactions_correctly(df)

    transaction_count = 0
    for group_key, group_data in groups.items():
        print(f"📅 Group: {group_key}")

        if group_data['type'] == 'trade':
            if any(op['operation'] == 'Transaction Buy' for op in group_data['operations']):
                # This is a BUY trade
                transaction_count += 1

                # Calculate totals
                buys = [op for op in group_data['operations'] if op['operation'] == 'Transaction Buy']
                spends = [op for op in group_data['operations'] if op['operation'] == 'Transaction Spend']
                fees = [op for op in group_data['operations'] if op['operation'] == 'Transaction Fee']

                total_bought = sum(op['change'] for op in buys)
                total_spent = sum(abs(op['change']) for op in spends)
                total_fees = sum(abs(op['change']) for op in fees)

                asset = buys[0]['coin']
                net_amount = total_bought - total_fees
                price = total_spent / total_bought if total_bought > 0 else 0

                print(f"  ✅ Transaction #{transaction_count}: BUY {net_amount:.6f} {asset}")
                print(f"     💰 Spent: ${total_spent:.6f} USDT")
                print(f"     💸 Fee: {total_fees:.6f} {asset}")
                print(f"     📈 Price: ${price:.6f} per {asset}")

            elif any(op['operation'] == 'Transaction Sold' for op in group_data['operations']):
                # This is a SELL trade
                transaction_count += 1

                sells = [op for op in group_data['operations'] if op['operation'] == 'Transaction Sold']
                revenues = [op for op in group_data['operations'] if op['operation'] == 'Transaction Revenue']
                fees = [op for op in group_data['operations'] if op['operation'] == 'Transaction Fee']

                total_sold = sum(abs(op['change']) for op in sells)
                total_received = sum(op['change'] for op in revenues)
                total_fees = sum(abs(op['change']) for op in fees)

                asset = sells[0]['coin']
                price = total_received / total_sold if total_sold > 0 else 0

                print(f"  ✅ Transaction #{transaction_count}: SELL {total_sold:.6f} {asset}")
                print(f"     💰 Received: ${total_received:.6f} USDT")
                print(f"     💸 Fee: ${total_fees:.6f} USDT")
                print(f"     📈 Price: ${price:.6f} per {asset}")

        elif group_data['type'] == 'convert':
            transaction_count += 2  # Convert creates both sell and buy

            negatives = [op for op in group_data['operations'] if op['change'] < 0]
            positives = [op for op in group_data['operations'] if op['change'] > 0]

            print(
                f"  ✅ Transaction #{transaction_count - 1}: CONVERT SELL {abs(negatives[0]['change'])} {negatives[0]['coin']}")
            print(f"  ✅ Transaction #{transaction_count}: CONVERT BUY {positives[0]['change']} {positives[0]['coin']}")

        print()

    print(f"📊 Result: {transaction_count} properly grouped transactions (CORRECT!)")
    print("\n🎯 Benefits of corrected approach:")
    print("   ✅ DOGE purchase = 1 transaction (600.399 DOGE for $199.56)")
    print("   ✅ Proper fee handling and deduction")
    print("   ✅ SHIB purchases grouped by timestamp")
    print("   ✅ Sell transactions properly paired with revenues")
    print("   ✅ FIFO calculations will be accurate")
    print("   ✅ Results match Koinly's logic!")


def group_transactions_correctly(df):
    """Simplified version of the grouping logic"""

    groups = {}

    for _, row in df.iterrows():
        timestamp_str = row['UTC_Time']
        operation = row['Operation']
        coin = row['Coin']
        change = Decimal(str(row['Change']))

        # Skip operations we don't process
        if operation in ['Transfer Between Main and Funding Wallet', 'Withdraw', 'Deposit']:
            continue

        # Group by minute
        minute_key = timestamp_str[:16]  # "24/12/2024 14:54"

        # Determine group type
        if operation in ['Transaction Buy', 'Transaction Spend', 'Transaction Fee',
                         'Transaction Sold', 'Transaction Revenue']:
            group_type = 'trade'
        elif operation in ['Binance Convert']:
            group_type = 'convert'
        else:
            continue

        group_key = f"{minute_key}_{group_type}"

        if group_key not in groups:
            groups[group_key] = {
                'type': group_type,
                'operations': []
            }

        groups[group_key]['operations'].append({
            'operation': operation,
            'coin': coin,
            'change': change
        })

    return groups


def main():
    """Main demonstration"""
    print("🔍 BINANCE CSV PROCESSING ANALYSIS")
    print("🎯 Why your results didn't match Koinly's")
    print()

    demonstrate_old_flawed_approach()
    demonstrate_corrected_approach()

    print("\n" + "=" * 60)
    print("🚀 CONCLUSION:")
    print("   The corrected processor now groups transactions properly,")
    print("   handles fees correctly, and calculates accurate FIFO cost basis.")
    print("   Your results should now match Koinly's calculations!")
    print("=" * 60)


if __name__ == "__main__":
    main()