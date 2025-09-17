#!/usr/bin/env python3
"""
Test Arbitrum integration using Playwright to test the web interface
"""
import asyncio
import os
import json

async def test_arbitrum_web_interface():
    """Test the Arbitrum integration through the web interface"""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            # Navigate to the application
            print("Navigating to the application...")
            await page.goto("http://localhost:3000")
            await page.wait_for_load_state("networkidle")

            # Take a screenshot to see the current state
            await page.screenshot(path="arbitrum_test_1.png")
            print("Screenshot saved: arbitrum_test_1.png")

            # Look for wallet addition interface
            print("Looking for wallet addition interface...")

            # Try to find an "Add Wallet" or similar button
            add_wallet_selectors = [
                "text=Add Wallet",
                "text=Connect Wallet",
                "text=Add Address",
                "[data-testid='add-wallet']",
                "button:has-text('Add')",
                ".add-wallet",
                "#add-wallet"
            ]

            add_wallet_button = None
            for selector in add_wallet_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        add_wallet_button = page.locator(selector).first
                        print(f"Found add wallet button with selector: {selector}")
                        break
                except:
                    continue

            if add_wallet_button:
                await add_wallet_button.click()
                await page.wait_for_timeout(1000)

                # Take screenshot after clicking add wallet
                await page.screenshot(path="arbitrum_test_2.png")
                print("Screenshot saved: arbitrum_test_2.png")

                # Look for address input field
                address_input_selectors = [
                    "input[placeholder*='address']",
                    "input[placeholder*='Address']",
                    "input[name='address']",
                    "input[type='text']",
                    "#address",
                    ".address-input"
                ]

                address_input = None
                for selector in address_input_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            address_input = page.locator(selector).first
                            print(f"Found address input with selector: {selector}")
                            break
                    except:
                        continue

                if address_input:
                    # Fill in the Arbitrum address
                    test_address = "0xc9C9fafcE2AF75CF2924de3DFef8Eb8f50BC77b2"
                    await address_input.fill(test_address)
                    print(f"Filled address: {test_address}")

                    # Look for chain/network selector
                    chain_selectors = [
                        "select[name='chain']",
                        "select[name='network']",
                        ".chain-selector",
                        ".network-selector",
                        "text=Arbitrum",
                        "text=arbitrum"
                    ]

                    chain_selector = None
                    for selector in chain_selectors:
                        try:
                            if await page.locator(selector).count() > 0:
                                chain_selector = page.locator(selector).first
                                print(f"Found chain selector with selector: {selector}")
                                break
                        except:
                            continue

                    if chain_selector:
                        # Select Arbitrum if it's a dropdown
                        try:
                            if "select" in selector.lower():
                                await chain_selector.select_option(value="arbitrum")
                            else:
                                await chain_selector.click()
                        except:
                            print("Could not select Arbitrum chain, continuing...")

                    # Look for submit/save button
                    submit_selectors = [
                        "button:has-text('Save')",
                        "button:has-text('Add')",
                        "button:has-text('Submit')",
                        "button[type='submit']",
                        ".submit-btn",
                        ".save-btn"
                    ]

                    submit_button = None
                    for selector in submit_selectors:
                        try:
                            if await page.locator(selector).count() > 0:
                                submit_button = page.locator(selector).first
                                print(f"Found submit button with selector: {selector}")
                                break
                        except:
                            continue

                    if submit_button:
                        await submit_button.click()
                        print("Clicked submit button")

                        # Wait for the request to complete
                        await page.wait_for_timeout(5000)

                        # Take screenshot after submission
                        await page.screenshot(path="arbitrum_test_3.png")
                        print("Screenshot saved: arbitrum_test_3.png")

                        # Look for transaction data or results
                        await page.wait_for_timeout(2000)

                        # Check for any visible transaction data
                        transaction_indicators = [
                            "text=ARB",
                            "text=1.95",
                            "text=0.99",
                            ".transaction",
                            ".tx-list",
                            ".transaction-row"
                        ]

                        found_transactions = False
                        for indicator in transaction_indicators:
                            try:
                                if await page.locator(indicator).count() > 0:
                                    print(f"Found transaction indicator: {indicator}")
                                    found_transactions = True
                            except:
                                continue

                        if found_transactions:
                            print("✓ Transaction data found on the page!")
                        else:
                            print("✗ No transaction data visible")

                        # Check network requests for API calls
                        print("\nChecking for API calls...")

            else:
                print("Could not find add wallet button")

        except Exception as e:
            print(f"Error during test: {str(e)}")
            await page.screenshot(path="arbitrum_test_error.png")

        finally:
            await browser.close()

def run_playwright_test():
    """Run the Playwright test"""
    print("Starting Playwright test for Arbitrum integration...")
    asyncio.run(test_arbitrum_web_interface())

if __name__ == "__main__":
    run_playwright_test()